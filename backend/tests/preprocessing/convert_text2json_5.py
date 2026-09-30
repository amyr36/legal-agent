"""
استخراج ساختار سلسله‌مراتبی از متن حقوقی فارسی — نسخهٔ ۵.

اصلاحات نسبت به نسخهٔ قبلی (v4)، بر اساس ایرادات مشاهده‌شده در legal_document_v3.json:

  1) رفع باگ اصلی anchorهای بخش‌بندی:
     الگوی قبلی با "|مقدمه" هر تکرار کلمهٔ «مقدمه» را (حتی وسط جملهٔ چک‌لیست
     ماهوی) به‌عنوان شروع یک بخش جدید تشخیص می‌داد. همین باعث می‌شد کل چک‌لیست
     اصول قانون اساسی به‌اشتباه زیر intro_reasons بیفتد و دو جمله («دلایل
     مندرج در» و «توضیحات راجع به ضرورت... در») درست وسط کلمهٔ «مقدمه» قطع
     شوند. حالا این شاخهٔ مبهم حذف شده و anchorها به عبارت‌های کامل و
     یکتا محدود شده‌اند.

  2) تشخیص و جداسازی بلوک «فهرست امضاکنندگان»:
     قبلاً فهرست ۵۷ نمایندهٔ امضاکننده به‌عنوان ادامهٔ متن آخرین بند دلایل
     توجیهی درج می‌شد. حالا با یک الگوی heuristic (تکرار متوالی «نام
     نام-») این بلوک شناسایی و در kind جدای «signatories» قرار می‌گیرد.

  3) فیلتر چانک‌های خالی/بی‌معنی قبل از ارسال:
     در خروجی قبلی حدود ۴۰٪ چانک‌ها عملاً خالی بودند و صرفاً هزینه/زمان
     تلف می‌کردند. حالا چانک‌هایی که حروف فارسی کافی ندارند اصلاً به مدل
     فرستاده نمی‌شوند.

  4) merge واقعی به‌جای فقط دسته‌بندی:
     خروجی هر kind حالا یک آبجکت واحد است (نه آرایه‌ای از چند تکه)؛ فیلدهای
     استاندارد (باب/فصل/ماده/بند/جزء/تبصره/پیوست/ارجاع_داخلی/ارجاع_بیرونی)
     از همهٔ چانک‌های آن kind به هم الحاق می‌شوند. کلیدهای غیراستاندارد
     (مثل "مقدمه" یا "عنوان" که مدل گاهی خودش می‌سازد) گم نمی‌شوند، بلکه
     زیر "_other_keys" نگه داشته می‌شوند تا هیچ داده‌ای بی‌صدا از دست نرود.

  5) چیدمان پرامپت برای بیشینه‌کردن شانس کش‌شدن:
     سیستم‌پرامپت (شامل مثال one-shot سنگین) حالا در تمام درخواست‌ها
     دقیقاً یک رشتهٔ ثابت و بدون هیچ درون‌گذاری پویاست؛ راهنمای بافتی هر
     چانک (که قبلاً به انتهای سیستم‌پرامپت اضافه می‌شد و آن را هر بار کمی
     متفاوت می‌کرد) حالا به ابتدای پیام user منتقل شده. این‌طور اگر
     provider/مدل از cache کردن prefix تکراری پشتیبانی کند (مثل قابلیت
     "context caching" خودِ DeepSeek که خودکار و بدون نیاز به پارامتر
     اضافه است)، سیستم‌پرامپت — که بخش سنگین/تکراریِ هزینه است — کاملاً
     یکسان می‌ماند و شانس cache-hit را حداکثر می‌کند.
     نکتهٔ مهم: این کار تضمین نمی‌کند gateway شما (avalai.ir) واقعاً کش
     می‌کند — این را باید از مستندات خودشان تأیید کنید. اگر پارامتر
     صریحی برای کش مثل یک فیلد در extra_body مستند کرده باشند، همان‌جا که
     در کد مشخص شده اضافه‌اش کنید.
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import os

API_KEY = os.environ["AVALAI_API_KEY"]
BASE_URL = "https://api.avalai.ir/v1"
MODEL = "deepseek-v4.1-flash"

INPUT_FILE = "backend/tests/doc_rag/hormuz1.txt"
OUTPUT_FILE = "backend/tests/output_last/legal_document_v6.json"

MAX_CHUNK_SIZE = 4000
MAX_WORKERS = 6

# حداقل تعداد حروف فارسیِ معنادار در یک چانک تا ارزش ارسال به مدل را داشته باشد.
MIN_MEANINGFUL_PERSIAN_CHARS = 15

STANDARD_KEYS = [
    "باب", "فصل", "ماده", "بند", "جزء", "تبصره",
    "پیوست", "ارجاع_داخلی", "ارجاع_بیرونی",
]


# ---------------------------------------------------------------------------
# ۱) شناسایی مرزهای معنایی سند (anchorهای دقیق‌تر و بدون false-positive)
# ---------------------------------------------------------------------------

# هر anchor فقط روی عبارت‌های کامل و کم‌تکرار تعریف شده، نه یک کلمهٔ تنها
# مثل «مقدمه» که ممکن است وسط جملات دیگر هم ظاهر شود.
SECTION_ANCHORS = [
    (r"عنوان\s*طرح\s*:", "operative_text",
     "این بخش متن مادهٔ واحد طرح است؛ عدد ابتدای خط (1، 2، 3...) شمارهٔ «ماده» "
     "است، نه «بند». متن‌های شروع‌شده با «تبصره» را داخل فیلد تبصرهٔ همان "
     "ماده به‌صورت آبجکت {\"شماره\": ..., \"متن\": ...} قرار بده، نه رشتهٔ ساده."),

    (r"نظر\s*اداره\s*کل\s*تدوین\s*قوانین", "review_tadvin",
     "این بخش نظر کارشناسی ادارهٔ تدوین قوانین است؛ عدد ابتدای خط شمارهٔ "
     "«بند» است، نه «ماده»."),

    (r"نظر\s*اداره\s*کل\s*اسناد\s*و\s*تنقیح\s*قوانین", "review_asnad",
     "این بخش نظر ادارهٔ اسناد و تنقیح قوانین است؛ عدد ابتدای خط شمارهٔ "
     "«بند» است، نه «ماده»."),

    (r"دلایل\s*توجیهی", "intro_reasons",
     "این بخش دلایل توجیهیِ مقدمهٔ طرح است؛ عدد ابتدای خط شمارهٔ «بند» است، "
     "نه «ماده»."),

    (r"ضمیمه\s*نظر", "attachment",
     "این بخش «پیوست» سند است. محتوای داخل هر آیتم (مثل الف/ب) را کامل در "
     "فیلد متن همان آیتم پیوست بیاور، آن را خلاصه یا حذف نکن."),
]

# بلوک فهرست امضاکنندگان: تکرار متوالی «نام نام-» که در این نوع سند رسمی
# معمولاً هیچ کلیدواژهٔ صریحی قبلش نمی‌آید.
_PERSIAN_WORD = r"[\u0600-\u06FF]+"
SIGNATORY_BLOCK_PATTERN = re.compile(
    rf"(?:{_PERSIAN_WORD}\s{_PERSIAN_WORD}-\s*){{4,}}"
)

SIGNATORY_GUIDANCE = (
    "این بخش فهرست نام نمایندگان امضاکنندهٔ طرح است، نه بند یا ماده. "
    'خروجی را دقیقاً به‌صورت {"امضاکنندگان": ["نام ۱", "نام ۲", ...]} برگردان.'
)

# مرزهای اتمی — هرگز وسط‌شان بریده نمی‌شود (از قبل به ابتدای خط anchor است).
ATOMIC_BOUNDARY_PATTERN = re.compile(
    r"(?m)^(?:"
    r"باب\s*\S+|"
    r"فصل\s*\S+|"
    r"ماده\s*[\)\(]?\s*\d+|"
    r"تبصره\s*[\-–:]?\s*(?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|\d+)|"
    r"پیوست\b|"
    r"\d{1,3}\s"
    r")"
)


@dataclass
class Section:
    kind: str
    guidance: str
    text: str


def _first_match_positions(text: str) -> list[tuple[int, str, str]]:
    """فقط اولین وقوع هر anchor را برمی‌دارد (هر بخش سند یک‌بار شروع می‌شود)."""
    positions = []
    for pattern, kind, guidance in SECTION_ANCHORS:
        m = re.search(pattern, text)
        if m:
            positions.append((m.start(), kind, guidance))
    positions.sort(key=lambda x: x[0])
    return positions


def split_into_sections(text: str) -> list[Section]:
    positions = _first_match_positions(text)

    if not positions or positions[0][0] > 0:
        positions.insert(0, (0, "generic",
                              "این بخش شامل اطلاعات کلی سند (شماره ثبت، کمیسیون‌ها) است."))

    sections = []
    for i, (start, kind, guidance) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        sections.append(Section(kind=kind, guidance=guidance, text=text[start:end]))

    # هر بخش را برای بلوک امضاکنندگان بررسی و در صورت وجود جدا کن.
    result = []
    for section in sections:
        result.extend(_carve_out_signatories(section))
    return result


def _carve_out_signatories(section: Section) -> list[Section]:
    match = SIGNATORY_BLOCK_PATTERN.search(section.text)
    if not match:
        return [section]

    before, sig_block, after = (
        section.text[: match.start()],
        section.text[match.start(): match.end()],
        section.text[match.end():],
    )

    pieces = []
    if before.strip():
        pieces.append(Section(kind=section.kind, guidance=section.guidance, text=before))
    pieces.append(Section(kind="signatories", guidance=SIGNATORY_GUIDANCE, text=sig_block))
    if after.strip():
        pieces.append(Section(kind=section.kind, guidance=section.guidance, text=after))
    return pieces


def split_into_atomic_units(section_text: str) -> list[str]:
    matches = list(ATOMIC_BOUNDARY_PATTERN.finditer(section_text))
    if not matches:
        return [section_text]

    units = []
    if matches[0].start() > 0:
        units.append(section_text[: matches[0].start()])

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section_text)
        units.append(section_text[m.start(): end])

    return [u for u in units if u.strip()]


def pack_units_into_chunks(units: list[str], max_size: int) -> list[str]:
    chunks = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > max_size:
            chunks.append(current)
            current = unit
        else:
            current += unit
    if current:
        chunks.append(current)
    return chunks


def is_meaningful(text: str, min_chars: int = MIN_MEANINGFUL_PERSIAN_CHARS) -> bool:
    persian_chars = re.findall(r"[\u0600-\u06FF]", text)
    return len(persian_chars) >= min_chars


@dataclass
class PreparedChunk:
    text: str
    kind: str
    guidance: str


def build_chunks(text: str) -> list[PreparedChunk]:
    prepared = []
    skipped = 0
    for section in split_into_sections(text):
        units = split_into_atomic_units(section.text)
        for packed in pack_units_into_chunks(units, MAX_CHUNK_SIZE):
            if not is_meaningful(packed):
                skipped += 1
                continue
            prepared.append(PreparedChunk(text=packed, kind=section.kind, guidance=section.guidance))
    if skipped:
        print(f"Skipped {skipped} empty/near-empty chunk(s) — no API call made for them.")
    return prepared


# ---------------------------------------------------------------------------
# ۲) پرامپت سیستم — کاملاً ثابت و بدون درون‌گذاری پویا (برای قابلیت کش)
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = r"""
You are a Persian legal document structure extraction system.

Convert the input Persian legal text into structured JSON.

Detect:
- باب
- فصل
- ماده
- بند
- جزء
- تبصره
- پیوست
- ارجاع داخلی
- ارجاع بیرونی

Rules:
- Preserve the original order and legal wording.
- Do not summarize, interpret, rewrite, correct, or invent information.
- Preserve the hierarchy between elements.
- Do not infer missing structures.
- Extract internal and external references without interpreting them.
- If a structure does not exist, use an empty list.
- Return ONLY valid JSON. No Markdown or explanation.
- Only classify a line as "ارجاع_داخلی" if it explicitly refers to another
  part of THIS SAME document (e.g. "تبصره یک این طرح"). Ordinary procedural
  sentences ("در اجرای بند...") are NOT internal references unless they name
  a specific numbered element of this document.
- Do NOT invent any top-level key other than: باب, فصل, ماده, بند, جزء,
  تبصره, پیوست, ارجاع_داخلی, ارجاع_بیرونی. If a piece of text does not fit
  cleanly into these, put it inside the "متن" field of the closest matching
  existing element instead of creating a new key. The only exception is a
  chunk explicitly marked in the user message as a signatories list, whose
  output must be exactly {"امضاکنندگان": [...]}.
- Never merge unrelated content (such as a list of names) into the "متن" of
  a نظر بند or another element — if the input clearly changes into a
  different kind of content mid-chunk, treat it as a separate item.

Hierarchy:

باب
└── فصل
    └── ماده
        ├── بند
        │   └── جزء
        └── تبصره

SCHEMA CONSISTENCY RULE:
Every output — at the top level AND inside every nested object — always
contains exactly these 9 keys, and باب, فصل, بند, جزء, تبصره, پیوست,
ارجاع_داخلی, ارجاع_بیرونی are ALWAYS arrays (never a bare object, even when
there is only one). Each item inside باب/فصل is itself an object with its own
"شماره", "عنوان", and a nested array for its children. If an element's number
cannot be determined from the text (e.g. a بند whose "number" is really just
an introductory phrase like "در اجرای بند..."), use "شماره": null rather than
guessing or omitting the field. If a ماده/فصل/باب in the CURRENT chunk is not
introduced by its own heading (e.g. the chunk continues a فصل whose title
appeared in a previous chunk), put its مواد directly in the top-level "ماده"
array instead of inventing a wrapping فصل/باب object.

THREE-SHOT EXAMPLES:

--- EXAMPLE 1: formal law with باب / فصل / ماده ---

INPUT:
باب دوم
احکام اجرایی

فصل اول
وظایف دستگاه‌های اجرایی

ماده 6- دستگاه‌های اجرایی موظفند برنامه اجرایی خود را تهیه نمایند.

ماده 7- برنامه اجرایی باید به تأیید مقام مسئول برسد.
تبصره- در صورت تأخیر، مسئولیت با دستگاه اجرایی است.

OUTPUT:
{
  "باب": [
    {
      "شماره": "دوم",
      "عنوان": "احکام اجرایی",
      "فصل": [
        {
          "شماره": "اول",
          "عنوان": "وظایف دستگاه‌های اجرایی",
          "ماده": [
            {
              "شماره": 6,
              "متن": "دستگاه‌های اجرایی موظفند برنامه اجرایی خود را تهیه نمایند.",
              "بند": [],
              "تبصره": [],
              "ارجاع_داخلی": [],
              "ارجاع_بیرونی": []
            },
            {
              "شماره": 7,
              "متن": "برنامه اجرایی باید به تأیید مقام مسئول برسد.",
              "بند": [],
              "تبصره": [
                {
                  "شماره": null,
                  "متن": "در صورت تأخیر، مسئولیت با دستگاه اجرایی است.",
                  "ارجاع_داخلی": [],
                  "ارجاع_بیرونی": []
                }
              ],
              "ارجاع_داخلی": [],
              "ارجاع_بیرونی": []
            }
          ]
        }
      ]
    }
  ],
  "فصل": [],
  "ماده": [],
  "بند": [],
  "جزء": [],
  "تبصره": [],
  "پیوست": [],
  "ارجاع_داخلی": [],
  "ارجاع_بیرونی": []
}

--- EXAMPLE 2: standalone ماده واحده (no باب/فصل), numbered تبصره with an internal cross-reference ---

INPUT:
عنوان طرح: طرح نمونهٔ عوارض گمرکی

1- واردات کالای ممنوعه ممنوع است.

2- ورود کالای مجاز منوط به پرداخت عوارض گمرکی است.
تبصره یک- نرخ عوارض برای سال اول سه درصد (3%) است.
تبصره دو- کالاهایی که از کشورهای تحریم‌شده وارد شوند، دو برابر عوارض تبصره یک این ماده را می‌پردازند.

OUTPUT:
{
  "باب": [],
  "فصل": [],
  "ماده": [
    {
      "شماره": 1,
      "متن": "واردات کالای ممنوعه ممنوع است.",
      "بند": [],
      "تبصره": [],
      "ارجاع_داخلی": [],
      "ارجاع_بیرونی": []
    },
    {
      "شماره": 2,
      "متن": "ورود کالای مجاز منوط به پرداخت عوارض گمرکی است.",
      "بند": [],
      "تبصره": [
        {
          "شماره": "یک",
          "متن": "نرخ عوارض برای سال اول سه درصد (3%) است.",
          "ارجاع_داخلی": [],
          "ارجاع_بیرونی": []
        },
        {
          "شماره": "دو",
          "متن": "کالاهایی که از کشورهای تحریم‌شده وارد شوند، دو برابر عوارض تبصره یک این ماده را می‌پردازند.",
          "ارجاع_داخلی": ["تبصره یک همین ماده"],
          "ارجاع_بیرونی": []
        }
      ],
      "ارجاع_داخلی": [],
      "ارجاع_بیرونی": []
    }
  ],
  "بند": [],
  "جزء": [],
  "تبصره": [],
  "پیوست": [],
  "ارجاع_داخلی": [],
  "ارجاع_بیرونی": []
}

--- EXAMPLE 3: administrative/expert review section — بند without a numeric شماره of its own, containing a checklist of جزء items ---

INPUT:
نظر ادارهکل تدوین قوانین
در اجرای بند (2) ماده (4) قانون تدوین و تنقیح قوانین و مقررات کشور مصوب 25/3/1389:
1 دارای موضوع و عنوان مشخص:
است
2 عنوان با مفاد طرح منطبق:
است
3 مطابقت با اصل 3 قانون اساسی:
ندارد
4 رعایت بند 9 سیاست‌های کلی نظام قانونگذاری:
نشده است

OUTPUT:
{
  "باب": [],
  "فصل": [],
  "ماده": [],
  "بند": [
    {
      "شماره": null,
      "متن": "در اجرای بند (2) ماده (4) قانون تدوین و تنقیح قوانین و مقررات کشور مصوب 25/3/1389",
      "جزء": [
        { "شماره": 1, "موضوع": "دارای موضوع و عنوان مشخص", "وضعیت": "است", "ارجاع_بیرونی": [] },
        { "شماره": 2, "موضوع": "عنوان با مفاد طرح منطبق", "وضعیت": "است", "ارجاع_بیرونی": [] },
        { "شماره": 3, "موضوع": "مطابقت با اصل 3 قانون اساسی", "وضعیت": "ندارد", "ارجاع_بیرونی": ["اصل 3 قانون اساسی"] },
        { "شماره": 4, "موضوع": "رعایت بند 9 سیاست‌های کلی نظام قانونگذاری", "وضعیت": "نشده است", "ارجاع_بیرونی": ["بند 9 سیاست‌های کلی نظام قانونگذاری"] }
      ],
      "ارجاع_داخلی": [],
      "ارجاع_بیرونی": ["بند 2 ماده 4 قانون تدوین و تنقیح قوانین و مقررات کشور مصوب 25/3/1389"]
    }
  ],
  "جزء": [],
  "تبصره": [],
  "پیوست": [],
  "ارجاع_داخلی": [],
  "ارجاع_بیرونی": []
}

Use whichever of these three shapes matches the CURRENT chunk's own content —
do not force باب/فصل wrapping onto a standalone-ماده chunk (Example 2), and
do not force a numbered ماده onto an administrative review chunk (Example 3);
follow the bracketed context note in the user message to decide.

The input may be a chunk of a larger document. The user message may start
with a short bracketed context note like "[این بخش ... است]" — that note is
NOT part of the document text; use it only to disambiguate whether numbers
mean ماده or بند in this chunk, then extract only from the text that follows.
Do not invent missing context.

Return only valid JSON.
"""


def build_user_message(chunk: PreparedChunk) -> str:
    if chunk.guidance:
        return f"[{chunk.guidance}]\n\n{chunk.text}"
    return chunk.text


# ---------------------------------------------------------------------------
# ۳) فراخوانی مدل
# ---------------------------------------------------------------------------

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def call_model(chunk: PreparedChunk) -> dict:
    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},  # همیشه دقیقاً یکسان
        {"role": "user", "content": build_user_message(chunk)},
    ]

    # اگر avalai.ir/مدل از response_format پشتیبانی نکند، بدون آن دوباره تلاش می‌کنیم.
    # اگر مستندات avalai.ir پارامتر صریحی برای کش‌کردن prompt دارد (مثلاً یک
    # فیلد داخل extra_body)، همین‌جا اضافه‌اش کنید، مثلا:
    #   extra_body={"cache": True}
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
        )

    result = response.choices[0].message.content
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"raw_output": result, "error": "invalid_json"}


# ---------------------------------------------------------------------------
# ۴) ادغام واقعی خروجی چانک‌ها به یک آبجکت به‌ازای هر kind
# ---------------------------------------------------------------------------

def merge_within_kind(chunk_dicts: list[dict]) -> dict:
    merged = {key: [] for key in STANDARD_KEYS}
    other_keys = []

    for d in chunk_dicts:
        if not isinstance(d, dict):
            continue
        extra = {}
        for key, value in d.items():
            if key in STANDARD_KEYS:
                if isinstance(value, list):
                    merged[key].extend(value)
                elif value not in (None, [], {}):
                    merged[key].append(value)
            else:
                extra[key] = value
        if extra:
            other_keys.append(extra)

    if other_keys:
        merged["_other_keys"] = other_keys

    return merged


def merge_results(chunk_outputs: list[dict], kinds: list[str]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for output, kind in zip(chunk_outputs, kinds):
        grouped.setdefault(kind, []).append(output)

    return {kind: merge_within_kind(dicts) for kind, dicts in grouped.items()}


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------

def main():
    text = Path(INPUT_FILE).read_text(encoding="utf-8")
    chunks = build_chunks(text)

    print(f"Document length: {len(text):,} characters")
    print(f"Chunks to send to the model: {len(chunks)}")

    outputs: list[dict] = [None] * len(chunks)
    kinds = [chunk.kind for chunk in chunks]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_index = {
            executor.submit(call_model, chunk): i
            for i, chunk in enumerate(chunks)
        }

        done_count = 0
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            done_count += 1
            try:
                outputs[i] = future.result()
            except Exception as exc:
                print(f"WARNING: chunk {i + 1} failed: {exc}")
                outputs[i] = {"error": str(exc)}
            print(f"Finished {done_count}/{len(chunks)} (chunk {i + 1}, kind={kinds[i]})")

    merged = merge_results(outputs, kinds)

    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_FILE).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nDone.")
    print(f"Output saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()