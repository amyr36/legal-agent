import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.services import vector_store as vss
from app.core.config import SOURCES_DIR, settings
from app.core.config import (
    EFFORT_LEVEL,
    EFFORT_ON,
    LLM_BATCH_SIZE,
    LLM_MAX_RETRIES,
    MAX_CONCURRENT_REQUESTS,
    RELATION_TYPE_VALUES,
    RESULTS_PATH,
    TOP_K,
)
from app.core.prompts import ANALYSIS_SYSTEM_PROMPT , build_batch_user_prompt
from app.schemas.analysis import BatchAnalysisResult, AnalysisResult
from app.services.retrieval import (
    deduplicate_pairs,
    records_by_id,
    retrieve_candidates,
)


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    if not settings.AVALAI_API_KEY:
        raise RuntimeError("AVALAI_API_KEY is not configured in settings")
    return ChatOpenAI(
        base_url=settings.AVALAI_BASE_URL,
        api_key=settings.AVALAI_API_KEY,
        model=settings.AVALAI_MODEL or settings.STRUCTURE_MODEL or "deepseek-v4.1-flash",
        reasoning_effort=EFFORT_LEVEL if EFFORT_ON else None,
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


def build_pair_prompt(record_a: Dict, record_b: Dict) -> str:
    return f"""### Pair:
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
        build_pair_prompt(p["source"], p["candidate"])
        for p in pairs
    ]
    messages = [("system", ANALYSIS_SYSTEM_PROMPT), ("user", build_batch_user_prompt(pair_blocks))]

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


def _match_results_to_pairs(batch: List[Dict], batch_results: List[AnalysisResult]) -> Tuple[List[Tuple[Dict, AnalysisResult]], List[AnalysisResult]]:
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


def analyze_all_pairs(pairs: List[Dict], chat_model=None, batch_size: int = LLM_BATCH_SIZE) -> List[AnalysisResult]:
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



def save_results(shaped_results: List[Dict], path: str = RESULTS_PATH) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for item in shaped_results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
<<<<<<< HEAD
    return path
=======
    return path


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------


def _demo() -> None:
    """Full mini-pipeline: load context -> retrieve -> call LLM -> print."""
    print("=== services.llm_analysis (standalone) ===")

    print("[2/4] retrieving candidates ...")
    pairs = (Path(SOURCES_DIR) / 'file.txt').read_text(encoding='utf-8')

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
>>>>>>> 4c801c167e3eb9d2b5be1549952bdcf03c6d22cd
