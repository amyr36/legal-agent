"""LLM analysis layer.

Runnable standalone:  python -m services.llm_analysis
(it runs retrieval first to get candidates, then calls the LLM on them and
prints the structured verdicts — without persisting to disk)
"""

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
    RELATION_BASIS_VALUES,
    RELATION_MODE_VALUES,
    RELATION_TYPE_VALUES,
    RESULTS_PATH,
    TOP_K,
)
from services.retrieval import (
    deduplicate_pairs,
    records_by_id,
    retrieve_candidates,
)


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel):
    """LLM verdict for one candidate pair (all analytical fields in Persian)."""

    source_id: int = Field(description="شناسه واقعی رکورد مبدأ")
    target_id: int = Field(description="شناسه واقعی رکورد مقصد")
    relation: Literal["مشابه", "متناقض", "بی‌ارتباط"] = Field(
        description="رابطه کلی بین دو رکورد"
    )
    relation_type: str = Field(
        description="نوع رابطه — یکی از: " + " | ".join(RELATION_TYPE_VALUES)
    )
    relation_basis: str = Field(
        description="مبنای حقوقی — یکی از: " + " | ".join(RELATION_BASIS_VALUES)
    )
    relation_mode: str = Field(
        description="نحوه ظهور — یکی از: " + " | ".join(RELATION_MODE_VALUES)
    )
    explanation: str = Field(description="توضیح فارسی مستند به هر دو رکورد")
    confidence: float = Field(description="درجه اطمینان ۰.۰ تا ۱.۰", ge=0.0, le=1.0)


class BatchAnalysisResult(BaseModel):
    results: List[AnalysisResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------


def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=CHAT_MODEL_BASE_URL,
        api_key=CHAT_MODEL_API_KEY,
        model=CHAT_MODEL_NAME,
    )


# ---------------------------------------------------------------------------
# System prompt (Persian legal-analysis)
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = f""" نقش

تو یک تحلیل‌گر متون حقوقی فارسی هستی. ورودی تو دو سند حقوقی (هرکدام چند ماده/تبصره) است. کارت این است که رابطه‌ی حکمی بین مواد دو سند را پیدا و طبقه‌بندی کنی.

قبل از هر تصمیم: هر ماده را کامل بخوان

قبل از مقایسه‌ی دو ماده با هم، مطمئن شو که معنای هر کدام به‌تنهایی را درست فهمیده‌ای:

آیا حکم الزام، اختیار، ممنوعیت یا توصیه است؟ (فعل «باید/مکلف» با «می‌تواند» و «نباید/ممنوع» فرق دارد)
آیا نفی وجود دارد؟ نفیِ‌مضاعف را با دقت بخوان («نمی‌تواند ... نکند» یعنی باید بکند، نه ممنوعیت)
آیا ماده قید، شرط یا استثنا دارد؟ («مگر آنکه»، «در صورتی که»، «به‌جز») — یک استثنا می‌تواند کل اثر اجرایی ماده را عوض کند. دو ماده که فقط در همین قید با هم فرق دارند، اثر کاملاً متفاوتی دارند حتی اگر ۹۰٪ متن‌شان یکی باشد.

این فهم را در نظر بگیر ولی خودش را به‌عنوان یک تگ جدا در خروجی ننویس — فقط در فیلد note به آن اشاره کن اگر تصمیم را عوض کرده.

تگ سطح اول (tier) — سه‌گانه

هر جفت ماده یکی از این سه حالت را دارد:

تشابه — دو ماده هم‌راستا و مکمل‌اند (مثل دو تکه از یک پازل)
تناقض — دو ماده با هم ناسازگارند یا یکی دیگری را از اثر انداخته
بی‌ربط — هیچ ارتباط حکمی خاصی ندارند → این را در خروجی ننویس، فقط رد کن.

تگ سطح دوم (relation) — با الگوریتم تصمیم، نه با مقایسه‌ی آزاد

به‌جای اینکه ۹ تعریف را با هم مقایسه کنی، گام‌های زیر را به‌ترتیب طی کن و در همان گامی که جواب «بله» گرفتی متوقف شو.

اگر tier = «تشابه»:

گام ۱ — آیا الفاظ و حکم دو ماده تقریباً یکسان‌اند، بدون هیچ تفاوت زمانی یا محتوایی؟
  بله → تکرار مقرراتی. تمام.
گام ۲ — آیا ماده‌ی B بدون ماده‌ی A ناقص یا بی‌معناست؟
  بله → تکمیل. تمام.
گام ۳ — آیا ماده‌ی B فقط حکم کلی A را برای یک زیرمجموعه‌ی خاص تغییر/محدود می‌کند؟
  بله → تخصیص. تمام.
گام ۴ (پیش‌فرض) — حکم یا اصل مشترکی با الفاظ متفاوت؟
  بله → اقتباس. تمام.

⚠️ قبل از گام ۲ و ۳ حتماً چک کن: آیا موضوع/نهاد حقوقی A و B واقعاً یکی است؟

اگر tier = «تناقض»:

گام ۱ — نسخ صریح با ذکر شماره؟ بله → نسخ صریح.
گام ۲ — ارجاع عددی شکسته/نامتناظر؟ بله → ابهام تفسیری.
گام ۳ — تبصره/الحاقیه‌ی متصل ولی متضاد؟ بله → ناسازگاری متن اصلی و اصلاحات.
گام ۴ — حکم متأخر، متقدم را بی‌اثر می‌کند؟ بله → نسخ ضمنی.
گام ۵ (پیش‌فرض) — دو حکم مستقیماً یکدیگر را نقض می‌کنند؟ بله → تعارض.

قاعده‌ی طلایی برای تشخیص «بی‌ربط» در برابر «رابطه‌ی ظریف»

اگر برای برقرارکردن رابطه مجبوری چند فرض اضافه بسازی، آن رابطه واقعی نیست — بنویس بی‌ربط و رد کن.

روش کار

۱. هر ماده‌ی سند اول را با هر ماده‌ی سند دوم مقایسه کن.
۲. اگر رابطه بی‌ربط بود، هیچ خروجی نده.
۳. اگر رابطه‌ای پیدا شد، اولین گامی که «بله» شد را ملاک بگیر.

فرمت خروجی (الزامی)

فقط JSONL، یک آبجکت در هر خط:

{{"pair": ["A-<شماره>", "B-<شماره>"], "tier": "تشابه یا تناقض", "relation": "یکی از ۹ نوع", "note": "۱ تا ۲ جمله با نقل قول دقیق"}}

قوانین خروجی:

هیچ متن خارج از خطوط JSON ننویس.
هر جفت فقط یک بار.
اگر رابطه‌ای نبود، رشته‌ی خالی برگردان."""


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
            "relation_basis": r.relation_basis,
            "relation_mode": r.relation_mode,
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
            f"{r.relation_type} | {r.relation_mode} | conf={r.confidence:.2f}"
        )
        print(f"      {r.explanation[:120]}")


if __name__ == "__main__":
    _demo()