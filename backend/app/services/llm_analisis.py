import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from services import vector_store as vss
from core.config import (
    CHAT_MODEL_API_KEY,
    CHAT_MODEL_BASE_URL,
    CHAT_MODEL_NAME,
    LLM_BATCH_SIZE,
    LLM_MAX_RETRIES,
    MAX_CONCURRENT_REQUESTS,
    RELATION_TYPE_VALUES,
    RESULTS_PATH,
    TOP_K,
    EFFORT
)
from core.prompts import ANALYSIS_SYSTEM_PROMPT
from schemas.analysis import BatchAnalysisResult, AnalysisResult
from services.retrieval import (
    deduplicate_pairs,
    records_by_id,
    retrieve_candidates,
)


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------


def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=CHAT_MODEL_BASE_URL,
        api_key=CHAT_MODEL_API_KEY,
        model=CHAT_MODEL_NAME,
        reasoning_effort=EFFORT
    )


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def text_block(record: Dict) -> str:
    lines = [f"TEXT: {record.get('text', '')}", "metadata:"]
    for field in vss.METADATA_FIELDS:
        if field == "id":
            continue
        value = record.get(field)
        if value is not None:
            lines.append(f"  {field}: {value}")
    return "\n".join(lines)


def build_pair_prompt(record_a: Dict, record_b: Dict, retrieval_score=None) -> str:
    score_note = (
        f" (retrieval score {retrieval_score:.4f} — فقط جهت اطلاع)"
        if retrieval_score is not None
        else ""
    )
    return f"""### Pair: source_id = {record_a.get("id")} , target_id = {record_b.get("id")}{score_note}
SOURCE (id {record_a.get("id")}):
{text_block(record_a)}

TARGET (id {record_b.get("id")}):
{text_block(record_b)}"""


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


def analyze_pairs_batch(pairs: List[Dict], chat_model=None) -> List[AnalysisResult]:
    if not pairs:
        return []
    if chat_model is None:
        chat_model = get_chat_model()

    structured_llm = chat_model.with_structured_output(BatchAnalysisResult)

    pair_blocks = [
        build_pair_prompt(p["source"], p["candidate"], p.get("retrieval_score"))
        for p in pairs
    ]
    user_prompt = (
        "زوج‌های زیر را تحلیل حقوقی کن. برای هر pair دقیقاً یک نتیجه برگردان شامل: "
        "source_id, target_id, relation (مشابه | متناقض | بی‌ارتباط), relation_type, "
        "relation_basis, relation_mode, explanation, confidence. "
        f"دقیقاً {len(pairs)} نتیجه، به همان ترتیب pairها.\n\n"
        + "\n\n".join(pair_blocks)
    )

    messages = [("system", ANALYSIS_SYSTEM_PROMPT), ("user", user_prompt)]

    last_exc: Optional[Exception] = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            return _extract_results(structured_llm.invoke(messages))
        except Exception as exc:
            last_exc = exc
            print(f"  [llm] attempt {attempt}/{LLM_MAX_RETRIES} failed ({exc}); retrying...")
            time.sleep(2 * attempt)
    raise last_exc


def _extract_results(response: Any) -> List[AnalysisResult]:
    if isinstance(response, BatchAnalysisResult):
        return response.results
    if isinstance(response, dict) and "results" in response:
        return [AnalysisResult(**r) for r in response["results"]]
    return []


def _match_results_to_pairs(
    batch: List[Dict], batch_results: List[AnalysisResult]
) -> Tuple[List[Tuple[Dict, AnalysisResult]], List[AnalysisResult]]:
    pairs_by_key = {(p["source"].get("id"), p["candidate"].get("id")): p for p in batch}
    matched: List[Tuple[Dict, AnalysisResult]] = []
    unmatched: List[AnalysisResult] = []
    used = set()
    for r in batch_results:
        key = (r.source_id, r.target_id)
        if key in pairs_by_key and key not in used:
            matched.append((pairs_by_key[key], r))
            used.add(key)
        else:
            unmatched.append(r)
    return matched, unmatched


def analyze_all_pairs(
    pairs: List[Dict], chat_model=None, batch_size: int = LLM_BATCH_SIZE
) -> List[AnalysisResult]:
    results: List[AnalysisResult] = []
    if not pairs:
        return results

    total_batches = (len(pairs) + batch_size - 1) // batch_size
    batches = [
        (i // batch_size + 1, pairs[i : i + batch_size])
        for i in range(0, len(pairs), batch_size)
    ]

    def _run_one(batch_no: int, batch: List[Dict]) -> List[AnalysisResult]:
        print(f"  [llm] batch {batch_no}/{total_batches}: {len(batch)} pair(s)...")
        try:
            batch_results = analyze_pairs_batch(batch, chat_model)
        except Exception as exc:
            print(f"  [llm] batch {batch_no} FAILED ({exc}); skipping it")
            return []
        matched, unmatched = _match_results_to_pairs(batch, batch_results)
        if unmatched:
            print(f"  [llm] warning: dropping {len(unmatched)} unmatched result(s)")
        return [r for _, r in matched]

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as ex:
        futures = [ex.submit(_run_one, no, b) for no, b in batches]
        for f in as_completed(futures):
            results.extend(f.result())
    return results


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------


def _format_reference(record: Dict) -> Dict:
    return {field: record.get(field) for field in vss.METADATA_FIELDS}


def shape_results(
    raw_results: List[AnalysisResult],
    records_a: List[Dict],
    records_b: List[Dict],
    candidate_pairs: Optional[List[Dict]] = None,
) -> List[Dict]:
    a_by_id = records_by_id(records_a)
    b_by_id = records_by_id(records_b)
    methods_by_key = {
        (p["source"].get("id"), p["candidate"].get("id")): p.get("retrieval_methods", [])
        for p in (candidate_pairs or [])
    }

    shaped: List[Dict] = []
    for r in raw_results:
        source_record = a_by_id.get(r.source_id) or b_by_id.get(r.source_id)
        target_record = a_by_id.get(r.target_id) or b_by_id.get(r.target_id)
        if source_record is None or target_record is None:
            print(f"  [shape] warning: cannot resolve ids {r.source_id}/{r.target_id}")
            continue
        shaped.append({
            "source_id": r.source_id,
            "target_id": r.target_id,
            "source_metadata": _format_reference(source_record),
            "target_metadata": _format_reference(target_record),
            "source_text": source_record.get("text"),
            "target_text": target_record.get("text"),
            "relation": r.relation,
            "relation_type": r.relation_type,
            "explanation": r.explanation,
            "confidence": r.confidence,
            "retrieval_methods": methods_by_key.get((r.source_id, r.target_id), []),
        })
    return shaped


def save_results(shaped_results: List[Dict], path: str = RESULTS_PATH) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for item in shaped_results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------


def _demo() -> None:
    """Full mini-pipeline: load context -> retrieve -> call LLM -> print."""
    print("=== services.llm_analysis (standalone) ===")

    print("[1/4] loading context + vector stores ...")
    records_a = vss.load_context("A")
    records_b = vss.load_context("B")
    embeddings = vss.get_embeddings()
    vector_stores = vss.build_or_load_all(embeddings, rebuild=False)

    print("[2/4] retrieving candidates ...")
    pairs = deduplicate_pairs(
        retrieve_candidates(vector_stores, records_a, records_b, top_k=TOP_K)
    )
    print(f"      {len(pairs)} candidate pair(s)")

    if not pairs:
        print("      nothing to analyze.")
        return

    print("[3/4] calling LLM ...")
    raw = analyze_all_pairs(pairs)

    print(f"[4/4] {len(raw)} verdict(s):")
    for r in raw:
        print(
            f"  {r.source_id} -> {r.target_id} | {r.relation} | "
            f"{r.relation_type} | conf={r.confidence:.2f}"
        )
        print(f"      {r.explanation[:120]}")


if __name__ == "__main__":
    _demo()