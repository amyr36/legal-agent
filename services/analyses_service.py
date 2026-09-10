import json
import os
import re
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from services import vector_store_service as vss

TOP_K = 20           
LLM_BATCH_SIZE = 10  
LLM_MAX_RETRIES = 3  

CHAT_MODEL_BASE_URL = "https://api.avalai.ir/v1"
CHAT_MODEL_API_KEY = "aa-TXcGYa761kThZ5MWuVDzE3jX5HNJPEpsOe1tbjKITwuPrA95"
CHAT_MODEL_NAME = "glm-5.3-flash"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_PATH = os.path.join(BASE_DIR, "analysis_results.jsonl")


RELATION_VALUES = ["مشابه", "متناقض", "بی‌ارتباط"]

RELATION_TYPE_VALUES = [
    "تکرار مقرراتی",
    "اقتباس",
    "تکمیل",
    "تخصیص",
    "تعارض",
    "نسخ صریح",
    "نسخ ضمنی",
    "ابهام تفسیری",
    "ناسازگاری اصلاحی",
    "هم‌ارزی حکمی",
    "سایر",
]

RELATION_BASIS_VALUES = [
    "حکم",
    "الزام",
    "اختیار",
    "ممنوعیت",
    "توصیه",
    "شرط",
    "قید",
    "استثناء",
    "نفی",
    "اثبات",
    "دامنه شمول",
    "محدودیت زمانی",
    "محدودیت مکانی",
    "موضوعی",
    "مفهومی",
    "ارجاع داخلی",
    "ارجاع بیرونی",
    "اصلاح یا الحاق",
    "ترکیبی",
]


RELATION_MODE_VALUES = ["صریح", "ضمنی", "ارجاعی", "ترکیبی"]


class AnalysisResult(BaseModel):
    source_id: int = Field(description="شناسه واقعی رکورد مبدأ (دقیقاً همان id داده‌شده در داده pair)")
    target_id: int = Field(description="شناسه واقعی رکورد مقصد (دقیقاً همان id داده‌شده در داده pair)")
    relation: Literal["مشابه", "متناقض", "بی‌ارتباط"] = Field(
        description=(
            "رابطه کلی: 'مشابه' (هر دو رکورد حکم/مفاد واحد یا هم‌ارز دارند)، "
            "'متناقض' (احکام دو رکورد واقعاً در تعارض‌اند)، "
            "'بی‌ارتباط' (رابطه حقوقی معناداری وجود ندارد)."
        )
    )
    relation_type: str = Field(
        description=(
            "نوع رابطه حقوقی — دقیقاً یکی از: "
            + " | ".join(RELATION_TYPE_VALUES)
            + ". برای 'بی‌ارتباط' مقدار 'سایر' را بده."
        )
    )
    relation_basis: str = Field(
        description=(
            "مبنای حقوقی رابطه — دقیقاً یکی از: "
            + " | ".join(RELATION_BASIS_VALUES)
            + ". برای 'بی‌ارتباط' مقدار 'مفهومی' را بده."
        )
    )
    relation_mode: str = Field(
        description=(
            "نحوه ظهور رابطه — دقیقاً یکی از: "
            + " | ".join(RELATION_MODE_VALUES)
            + ". توجه: mode مستقل از type است (مثلاً تعارض ضمنی یا تکمیل ارجاعی معتبرند). "
            "برای 'بی‌ارتباط' مقدار 'ضمنی' را بده."
        )
    )
    explanation: str = Field(
        description=(
            "توضیح فارسی و مستند به متن و ساختار واقعی هر دو رکورد: دلیل رابطه، "
            "اشاره به شرط/قید/استثناء/نفی/دامنه شمول/ارجاع در صورت وجود، و "
            "برای 'بی‌ارتباط' دلیل بی‌ارتباطی."
        )
    )
    confidence: float = Field(
        description="درجه اطمینان بین ۰.۰ تا ۱.۰",
        ge=0.0,
        le=1.0,
    )


class BatchAnalysisResult(BaseModel):

    results: List[AnalysisResult] = Field(default_factory=list)



def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=CHAT_MODEL_BASE_URL,
        api_key=CHAT_MODEL_API_KEY,
        model=CHAT_MODEL_NAME,
    )


ANALYSIS_SYSTEM_PROMPT = f"""تو یک متخصص تحلیل اسناد حقوقی فارسی هستی. وظیفه تو مقایسه دو رکورد حقوقی و تعیین نوع رابطه آن‌هاست.

## اهمیتی که pairها برای تو دارند
این دو متن صرفاً به این دلیل کنار هم قرار گرفته‌اند که موتور جست‌وجوی معنایی و واژگانی آن‌ها را candidate تشخیص داده است. candidate بودن به معنی مشابه یا متناقض بودن نیست. تو باید مستقلاً و بر اساس تحلیل حقوقی واقعی، رابطه را تعیین کنی.

## مقادیر مجاز relation
- «مشابه»: هر دو رکورد اساساً حکم، تکلیف، حق یا مفاد واحد یا هم‌ارز دارند (تکرار مقرراتی یا هم‌ارزی حکمی واقعی، نه شباهت واژگانی).
- «متناقض»: احکام/مفاد دو رکورد واقعاً در تعارض‌اند — اجرای یکی، اجرای دیگری را ناممکن یا نقض آن می‌کند، یا یکی آنچه دیگری حرام/ممنوع/نفی کرده را الزام/تسریح می‌کند و بالعکس.
- «بی‌ارتباط»: رابطه حقوقی معنادار وجود ندارد.

## نکته بسیار مهم درباره فراتر رفتن از واژگان
تحلیل تو باید semantic و حقوقی باشد، نه صرفاً lexical. شباهت سطحی واژگان را با هم‌ارزی حقوقی اشتباه نگیر. در تحلیل حتماً بررسی کن:
- تفاوت حکم/الزام (obligation)، اختیار (permission)، ممنوعیت (prohibition) و توصیه (recommendation)؛ تغییری در این سطح یعنی رابطه عوض می‌شود.
- شرط‌ها، قیود و استثناءها: یک «در صورتی که» یا «مگر آنکه» می‌تواند مفاد را کلاً تغییر دهد.
- نفی و اثبات: وجود «نمی‌تواند/ممنوع/غیر از این مستثنی است» در برابر «می‌تواند/باید/الزام دارد».
- دامنه شمول: هر دو حکم ممکن است موضوع واحد داشته باشند ولی دامنه شمول متفاوت (عام در برابر خاص) داشته باشند.
- ساختار حقوقی: type رکورد (ماده/تبصره/بند/جزء/اصل)، parent_number (زیرمجموعه بودن یک رکورد از ماده یا بند دیگر)، book/chapter/subchapter و breadcrumb. تحلیل را صرفاً بر اساس یک جمله جدا‌شده انجام نده؛ ساختار و جایگاه حقوقی رکورد در تحلیل دخیل باشد.
- ارجاعات داخلی و بیرونی: اگر یک متن به ماده، بند یا قانون دیگری ارجاع می‌دهد، آن را در تحلیل دخیل کن.
- روابط صریح در برابر ضمنی: گاهی دو متن بدون اشاره مستقیم به یکدیگر، در عمل بر یک موضوع واحد حاکم‌اند؛ این را «ضمنی» بنام، نه صریح.

## relation_type — دقیقاً یکی از:
{chr(10).join("- " + v for v in RELATION_TYPE_VALUES)}

راهنمای تصمیم:
- «تکرار مقرراتی»: مفاد دو رکورد تکرار صریح یا تقریباً یکسان است.
- «اقتباس»: یکی مفاد دیگری را عیناً یا با تغییر اندک از منبع دیگری گرفته است.
- «تکمیل»: یکی حکم دیگری را کامل‌تر یا جزئی‌تر می‌کند بدون تعارض.
- «تخصیص»: یکی حالت خاص دیگری است (عام/خاص یا مطلق/مقید).
- «تعارض»: احکام دو رکورد با هم ناسازگارند اما نسخ روشن نیست.
- «نسخ صریح»: یکی صراحتاً حکم دیگری را لغو/نسخ کرده است (ارجاع به نسخ یا اصلاح).
- «نسخ ضمنی»: یکی مفاد دیگری را عملاً بی‌اثر می‌کند بدون تصریح به نسخ.
- «ابهام تفسیری»: ترکیب دو رکورد ابهام تفسیری ایجاد می‌کند (مثلاً دو تفسیر ممکن).
- «ناسازگاری اصلاحی»: ناسازگاری ناشی از اصلاحیه یا الحاق‌های بعدی.
- «هم‌ارزی حکمی»: حکم دو رکورد یکسان است اما با الفاظ یا در قالب‌های متفاوت.
- «سایر»: هیچ‌کدام از موارد بالا (و برای «بی‌ارتباط»).

## relation_basis — دقیقاً یکی از:
{chr(10).join("- " + v for v in RELATION_BASIS_VALUES)}

راهنمای تصمیم:
- «حکم»: رابطه بر محور حکم اصلی دو متن است.
- «الزام/اختیار/ممنوعیت/توصیه»: رابطه بر محور نوع تکلیف است (الزام، مجوز، منع، توصیه).
- «شرط/قید/استثناء»: رابطه ناشی از شرط («در صورتی که»)، قید (محدودکننده) یا استثناء («مگر آنکه») است.
- «نفی/اثبات»: رابطه ناشی از تقابل نفی و اثبات است.
- «دامنه شمول»: رابطه ناشی از اختلاف در دامنه یا شمول حکم است.
- «محدودیت زمانی/مکانی»: رابطه بر محور مهلت، تاریخ، یا محدوده جغرافیایی است.
- «موضوعی/مفهومی»: رابطه بر محور موضوع یا مفهوم مشترک است (نه حکم).
- «ارجاع داخلی/بیرونی»: رابطه از طریق ارجاع به رکورد دیگر داخل همان سند یا سند دیگر برقرار می‌شود.
- «اصلاح یا الحاق»: رابطه ناشی از اصلاحیه/الحاق‌های بعدی است.
- «ترکیبی»: رابطه ترکیبی از چند مبنای بالا است.

## relation_mode — دقیقاً یکی از:
{chr(10).join("- " + v for v in RELATION_MODE_VALUES)}

- «صریح»: رابطه با تصریح مستقیم در متن (حتی با اشاره صریح به رکورد دیگر) برقرار است.
- «ضمنی»: رابطه بدون تصریح مستقیم، از مفاد و اقتضای دو متن استنباط می‌شود.
- «ارجاعی»: رابطه از طریق ارجاع متنی به رکورد یا قانون دیگر برقرار است.
- «ترکیبی»: رابطه هم جنبه صریح دارد هم ضمنی/ارجاعی.

## relation در برابر relation_type در برابر relation_mode
این سه مفهوم مستقل‌اند و نباید با هم اشتباه شوند:
- relation = رابطه کلی (مشابه/متناقض/بی‌ارتباط).
- relation_type = نوع حقوقی رابطه (تعارض، تکمیل، تکرار مقرراتی و ...).
- relation_mode = نحوه ظهور رابطه (صریح/ضمنی/ارجاعی/ترکیبی).
مثلاً «تعارض ضمنی» (تعارضی که از اقتضای دو حکم استنباط می‌شود نه تصریح) و «تکمیل ارجاعی» (تکمیلی که از طریق ارجاع متنی برقرار است) هر دو کاملاً معتبرند.

## قواعد اجباری
- همه خروجی‌های تحلیلی (explanation و مقادیر taxonomy) باید فارسی باشند.
- explanation باید بر اساس متن و metadata واقعی دو رکورد باشد و رابطه حقوقی را توضیح دهد. در صورت وجود، به شرط، قید، استثناء، نفی، دامنه شمول یا ارجاع حقوقی اشاره کن.
- صرف شباهت واژگان یا موضوع مشترک، مبنای اعلام «مشابه» نیست؛ حکم باید هم‌ارز باشد.
- صرف مرتبط بودن دو متن، مبنای اعلام «متناقض» نیست؛ احکام باید واقعاً در تعارض باشند.
- اگر شواهد کافی برای ادعای قطعی وجود ندارد، با confidence پایین‌تر نظر بده یا رابطه را «بی‌ارتباط» اعلام نکن مگر مطمئن باشی؛ در توضیح به عدم کفایت شواهد اشاره کن.
- source_id و target_id باید دقیقاً همان شناسه‌های داده‌شده در داده pair باشند. هرگز id، آدرس یا منبعی را نساز یا حدس نزن.
- هیچ metadata، آدرس یا منبعی را جعل نکن.
- برای هر pair دقیقاً یک نتیجه بده و ترتیب pairها را حفظ کن.
- confidence بین ۰.۰ تا ۱.۰ بده."""


def text_block(record: Dict) -> str:
    lines = [f"TEXT: {record.get('text', '')}", "metadata:"]
    for field in vss.METADATA_FIELDS:
        if field == "id":
            continue  # already in the header line
        value = record.get(field)
        if value is not None:
            lines.append(f"  {field}: {value}")
    return "\n".join(lines)


def build_pair_prompt(record_a: Dict, record_b: Dict, retrieval_score=None) -> str:
    score_note = (
        f" (اطلاعات candidate از retrieval: score {retrieval_score:.4f} — فقط جهت اطلاع، سند نیست)"
        if retrieval_score is not None
        else ""
    )
    return f"""### Pair: source_id = {record_a.get("id")} , target_id = {record_b.get("id")}{score_note}
SOURCE (id {record_a.get("id")}):
{text_block(record_a)}

TARGET (id {record_b.get("id")}):
{text_block(record_b)}"""


def _records_by_id(records: List[Dict]) -> Dict[Any, Dict]:
    return {record.get("id"): record for record in records if record.get("id") is not None}


_TOKEN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077FA-Za-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(str(text)) if t.strip()]


class BM25Index:

    def __init__(self, records: List[Dict]):
        from rank_bm25 import BM25Okapi

        self._records = records
        self._by_index = {i: r for i, r in enumerate(records)}
        corpus_tokens = [_tokenize(r.get("text", "")) for r in records]
        self._bm25 = BM25Okapi(corpus_tokens) if records else None

    def search(self, query: str, k: int) -> List[Tuple[Dict, float]]:
        if not self._bm25 or not str(query).strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        hits = [(self._by_index[i], float(scores[i])) for i in order if scores[i] > 0]
        if not hits:
            hits = [(self._by_index[i], 1e-9) for i in order]
        return hits


def _semantic_search(vector_store, query_text: str, top_k: int) -> List[Tuple[Any, float]]:
    hits = vector_store.similarity_search_with_score(query_text, k=top_k)
    return [(doc.metadata.get("id"), float(score)) for doc, score in hits]


def _reference_candidates(source_record: Dict, target_records: List[Dict]) -> List[Dict]:
    text = str(source_record.get("text", ""))
    candidates: List[Dict] = []
    for match in re.finditer(r"(ماده|اصل|تبصره|بند)\s*([۰-۹0-9]+)", text):
        kind, raw_number = match.group(1), match.group(2)
        number = _fa_to_int(raw_number)
        if number is None:
            continue
        for record in target_records:
            record_number = record.get("number")
            if record_number is None or record_number != number:
                continue
            record_type = str(record.get("type") or "")
            if kind == "ماده" and "ماده" not in record_type:
                continue 
            candidates.append(record)
    return candidates


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _fa_to_int(raw: str) -> Optional[int]:
    try:
        return int(str(raw).translate(_FA_DIGITS))
    except (ValueError, TypeError):
        return None


def retrieve_candidates(
    vector_stores: Dict[str, Any],
    records_a: List[Dict],
    records_b: List[Dict],
    top_k: int = TOP_K,
) -> List[Dict]:
    pool = {"A": records_a, "B": records_b}
    bm25 = {"A": BM25Index(records_a), "B": BM25Index(records_b)}
    by_id = {key: _records_by_id(pool[key]) for key in pool}

    pairs_by_key: Dict[Tuple[Any, Any], Dict] = {}

    def _add_pair(rec_source: Dict, rec_target: Dict, score: float, method: str) -> None:
        a = rec_source if rec_source in records_a else rec_target
        b = rec_target if rec_source in records_a else rec_source
        key = (a.get("id"), b.get("id"))
        entry = pairs_by_key.get(key)
        if entry is None:
            entry = {
                "source": a,
                "candidate": b,
                "retrieval_score": score,
                "retrieval_methods": [method],
            }
            pairs_by_key[key] = entry
        else:
            if score < entry["retrieval_score"]:
                entry["retrieval_score"] = score
            if method not in entry["retrieval_methods"]:
                entry["retrieval_methods"].append(method)

    for source_key, target_key in (("A", "B"), ("B", "A")):
        source_records = pool[source_key]
        target_records = pool[target_key]
        vector_store = vector_stores[target_key]
        bm25_index = bm25[target_key]

        for record in source_records:
            query_text = str(record.get("text", ""))
            if not query_text.strip():
                continue

            for target_id, distance in _semantic_search(vector_store, query_text, top_k):
                target_record = by_id[target_key].get(target_id)
                if target_record is not None:
                    _add_pair(record, target_record, distance, "faiss")

            for target_record, score in bm25_index.search(query_text, top_k):
                _add_pair(record, target_record, score, "bm25")

            for target_record in _reference_candidates(record, target_records):
                _add_pair(record, target_record, 0.0, "reference")

    return list(pairs_by_key.values())


def deduplicate_pairs(pairs: List[Dict]) -> List[Dict]:
    seen: set = set()
    unique_pairs: List[Dict] = []
    for pair in pairs:
        key = (pair["source"].get("id"), pair["candidate"].get("id"))
        if key in seen:
            continue
        seen.add(key)
        unique_pairs.append(pair)
    dedup_count = len(pairs) - len(unique_pairs)
    if dedup_count:
        print(f"  [dedup] removed {dedup_count} duplicate pair(s); {len(unique_pairs)} unique pair(s) remain")
    return unique_pairs


def analyze_pairs_batch(pairs: List[Dict], chat_model=None) -> List[AnalysisResult]:

    if not pairs:
        return []
    if chat_model is None:
        chat_model = get_chat_model()

    structured_llm = chat_model.with_structured_output(BatchAnalysisResult)

    pair_blocks = [
        build_pair_prompt(pair["source"], pair["candidate"], pair.get("retrieval_score"))
        for pair in pairs
    ]
    user_prompt = (
        "زوج‌های زیر را تحلیل حقوقی کن. برای هر pair دقیقاً یک نتیجه برگردان شامل: "
        "source_id, target_id, relation (مشابه | متناقض | بی‌ارتباط), relation_type, "
        "relation_basis, relation_mode, explanation, confidence. "
        f"دقیقاً {len(pairs)} نتیجه، به همان ترتیب pairها، برگردان.\n\n"
        + "\n\n".join(pair_blocks)
    )

    messages = [
        ("system", ANALYSIS_SYSTEM_PROMPT),
        ("user", user_prompt),
    ]

    last_exc: Exception = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = structured_llm.invoke(messages)
            break
        except Exception as exc:
            last_exc = exc
            print(f"  [llm] attempt {attempt}/{LLM_MAX_RETRIES} failed ({exc}); retrying...")
            time.sleep(2 * attempt)
    else:
        raise last_exc 

    return response.results if isinstance(response, BatchAnalysisResult) else []


def _match_results_to_pairs(
    batch: List[Dict], batch_results: List[AnalysisResult]
) -> Tuple[List[Tuple[Dict, AnalysisResult]], List[AnalysisResult]]:
    pairs_by_key = {
        (pair["source"].get("id"), pair["candidate"].get("id")): pair for pair in batch
    }
    matched: List[Tuple[Dict, AnalysisResult]] = []
    unmatched: List[AnalysisResult] = []
    used_keys = set()
    for result in batch_results:
        key = (result.source_id, result.target_id)
        if key in pairs_by_key and key not in used_keys:
            matched.append((pairs_by_key[key], result))
            used_keys.add(key)
        else:
            unmatched.append(result)
    return matched, unmatched


def analyze_all_pairs(
    pairs: List[Dict], chat_model=None, batch_size: int = LLM_BATCH_SIZE
) -> List[AnalysisResult]:
    results: List[AnalysisResult] = []
    total_batches = (len(pairs) + batch_size - 1) // batch_size if pairs else 0
    for batch_index in range(0, len(pairs), batch_size):
        batch = pairs[batch_index : batch_index + batch_size]
        batch_no = batch_index // batch_size + 1
        print(f"  [llm] batch {batch_no}/{total_batches}: analyzing {len(batch)} pair(s)...")
        try:
            batch_results = analyze_pairs_batch(batch, chat_model)
        except Exception as exc:  
            print(f"  [llm] batch {batch_no} FAILED ({exc}); skipping it")
            continue
        
        matched, unmatched = _match_results_to_pairs(batch, batch_results)
        if unmatched:
            print(
                f"  [llm] warning: {len(unmatched)} result(s) referenced ids not in "
                f"batch {batch_no}; dropping them"
            )
        for pair, result in matched:
            if result.source_id != pair["source"].get("id") or result.target_id != pair["candidate"].get("id"):
                result.source_id = pair["source"].get("id")
                result.target_id = pair["candidate"].get("id")
        results.extend(result for _, result in matched)
    return results


def _format_reference(record: Dict) -> Dict:
    return {field: record.get(field) for field in vss.METADATA_FIELDS}


def shape_results(
    raw_results: List[AnalysisResult],
    records_a: List[Dict],
    records_b: List[Dict],
    candidate_pairs: Optional[List[Dict]] = None,
) -> List[Dict]:
    a_by_id = _records_by_id(records_a)
    b_by_id = _records_by_id(records_b)
    methods_by_key = {
        (p["source"].get("id"), p["candidate"].get("id")): p.get("retrieval_methods", [])
        for p in (candidate_pairs or [])
    }

    shaped: List[Dict] = []
    for result in raw_results:
        source_record = a_by_id.get(result.source_id) or b_by_id.get(result.source_id)
        target_record = a_by_id.get(result.target_id) or b_by_id.get(result.target_id)
        if source_record is None or target_record is None:
            print(
                f"  [shape] warning: could not resolve ids "
                f"{result.source_id}/{result.target_id}; skipping result"
            )
            continue
        shaped.append(
            {
                "source_id": result.source_id,
                "target_id": result.target_id,
                "source_metadata": _format_reference(source_record),
                "target_metadata": _format_reference(target_record),
                "source_text": source_record.get("text"),
                "target_text": target_record.get("text"),
                "relation": result.relation,
                "relation_type": result.relation_type,
                "relation_basis": result.relation_basis,
                "relation_mode": result.relation_mode,
                "explanation": result.explanation,
                "confidence": result.confidence,
                "retrieval_methods": methods_by_key.get(
                    (result.source_id, result.target_id), []
                ),
            }
        )
    return shaped


def save_results(shaped_results: List[Dict], path: str = RESULTS_PATH) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for item in shaped_results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path

class AnalysisState(TypedDict, total=False):

    rebuild: bool
    records_a: List[Dict]
    records_b: List[Dict]
    embeddings: Any
    chat_model: Any
    top_k: int
    vector_stores: Dict[str, Any]
    candidate_pairs: List[Dict]
    raw_results: List[AnalysisResult]
    results: List[Dict]
    results_path: str


def _load_context_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_context")
    records_a = vss.load_context("A")
    records_b = vss.load_context("B")
    print(f"  A: {len(records_a)} record(s), B: {len(records_b)} record(s)")
    return {"records_a": records_a, "records_b": records_b}


def _load_vector_stores_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_vector_stores")
    embeddings = state.get("embeddings") or vss.get_embeddings()
    vector_stores = vss.build_or_load_all(embeddings, rebuild=state.get("rebuild", False))
    for key, vs in vector_stores.items():
        print(f"  FAISS {key}: {len(vs.index_to_docstore_id)} vectors")
    return {"embeddings": embeddings, "vector_stores": vector_stores}


def _retrieve_candidates_node(state: AnalysisState) -> Dict:
    print("[analysis] node: retrieve_candidates")
    pairs = retrieve_candidates(
        state["vector_stores"],
        state["records_a"],
        state["records_b"],
        top_k=state.get("top_k", TOP_K),
    )
    unique_pairs = deduplicate_pairs(pairs)
    method_counts: Dict[str, int] = {}
    for pair in unique_pairs:
        for method in pair.get("retrieval_methods", []):
            method_counts[method] = method_counts.get(method, 0) + 1
    print(f"  {len(unique_pairs)} unique candidate pair(s); methods: {method_counts}")
    return {"candidate_pairs": unique_pairs}


def _analyze_with_llm_node(state: AnalysisState) -> Dict:
    print("[analysis] node: analyze_with_llm")
    chat_model = state.get("chat_model") or get_chat_model()
    raw_results = analyze_all_pairs(state["candidate_pairs"], chat_model)
    print(f"  {len(raw_results)} structured result(s)")
    return {"raw_results": raw_results}


def _build_results_node(state: AnalysisState) -> Dict:
    print("[analysis] node: build_results")
    results = shape_results(
        state["raw_results"],
        state["records_a"],
        state["records_b"],
        candidate_pairs=state.get("candidate_pairs", []),
    )
    results_path = save_results(results)
    print(f"  saved {len(results)} result(s) to {results_path}")
    return {"results": results, "results_path": results_path}


def build_analysis_graph() -> StateGraph:

    graph = StateGraph(AnalysisState)
    graph.add_node("load_context", _load_context_node)
    graph.add_node("load_vector_stores", _load_vector_stores_node)
    graph.add_node("retrieve_candidates", _retrieve_candidates_node)
    graph.add_node("analyze_with_llm", _analyze_with_llm_node)
    graph.add_node("build_results", _build_results_node)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "load_vector_stores")
    graph.add_edge("load_vector_stores", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "analyze_with_llm")
    graph.add_edge("analyze_with_llm", "build_results")
    graph.add_edge("build_results", END)
    return graph


def run_analysis(
    rebuild: bool = False,
    embeddings=None,
    chat_model=None,
    top_k: int = TOP_K,
) -> Dict:
    rebuild = rebuild or os.environ.get("LEGAL_SIM_REBUILD", "") == "1"
    graph = build_analysis_graph().compile()
    return graph.invoke(
        {
            "rebuild": rebuild,
            "embeddings": embeddings,
            "chat_model": chat_model,
            "top_k": top_k,
        }
    )


def _validate_records(records: List[Dict], label: str) -> None:
    for index, record in enumerate(records):
        if record.get("id") is None:
            raise ValueError(f"{label}[{index}] is missing the 'id' field")
        if not str(record.get("text", "")).strip():
            raise ValueError(f"{label}[{index}] is missing the 'text' field")


def analyze_documents(
    records_a: Optional[List[Dict]] = None,
    records_b: Optional[List[Dict]] = None,
    rebuild: bool = False,
) -> List[Dict]:
    if records_a:
        _validate_records(records_a, "document_a")
        vss.save_context("A", records_a)
    if records_b:
        _validate_records(records_b, "document_b")
        vss.save_context("B", records_b)

    state = run_analysis(rebuild=rebuild)
    return state.get("results", [])
