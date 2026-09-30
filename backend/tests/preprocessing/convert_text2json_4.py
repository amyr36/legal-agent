"""
استخراج ساختار سلسله‌مراتبی از متن حقوقی فارسی با چانکینگ ساختارآگاه.

تفاوت اصلی نسبت به نسخهٔ قبلی:
  1) به‌جای برش کورکورانه بر اساس تعداد کاراکتر، سند اول بر اساس مرزهای
     معنایی واقعی (باب/فصل/ماده/تبصره/پیوست + مرزهای بخش‌های اداری) به
     قطعات اتمی (atomic units) شکسته می‌شود. هیچ قطعه‌ای وسط بریده نمی‌شود.
  2) هر بخش سند یک "نوع" (kind) دارد که مشخص می‌کند اعداد ابتدای خط در آن
     بخش معادل «ماده»اند یا «بند» — همان ابهامی که باعث اشتباه برچسب‌گذاری
     می‌شد.
  3) بعد از دریافت خروجی مدل برای هر چانک، همهٔ نتایج در یک تابع merge به
     یک درخت واحد (باب > فصل > ماده > بند/تبصره) تبدیل می‌شوند؛ خروجی نهایی
     دیگر یک آرایهٔ رشته‌ای از تکه‌های قطع‌شده نیست.

محدودیت شناخته‌شده:
  در این سند خاص (hormuz1.txt)، هم مواد طرح و هم بندهای نظر کارشناسی با
  یک عدد خام (بدون کلمهٔ «ماده» یا «بند») شروع می‌شوند. تشخیص کامل این مورد
  فقط با regex ممکن نیست؛ اینجا با تشخیص نوع بخش (kind) بر اساس عناوین
  بخش (مثل «نظر ادارهکل تدوین قوانین») این ابهام تا حد زیادی رفع شده، اما
  برای اسناد دیگر ممکن است لازم باشد الگوهای kind را گسترش دهید.
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI


API_KEY = "aa-UyS2fJjtEn41olAYj1e6f4cBzAiQyu7hi1S6QTm6OAk4DtD6"
BASE_URL = "https://api.avalai.ir/v1"
MODEL = "deepseek-v4.1-flash"

INPUT_FILE = "backend/tests/doc_rag/hormuz1.txt"
OUTPUT_FILE = "backend/tests/output_last/legal_document_v3.json"

# سقف نرم برای اندازهٔ هر چانک (کاراکتر). هرگز باعث شکستن یک قطعهٔ اتمی نمی‌شود؛
# اگر یک قطعهٔ اتمی به‌تنهایی بزرگ‌تر از این سقف باشد، همچنان کامل نگه داشته می‌شود.
MAX_CHUNK_SIZE = 1500

# تعداد درخواست‌های هم‌زمان به مدل. عددی بین 4 تا 10 معمولاً امن است؛
# اگر خطای rate-limit گرفتید این عدد را کم کنید، اگر نگرفتید می‌توانید زیاد کنید.
MAX_WORKERS = 6


# ---------------------------------------------------------------------------
# ۱) شناسایی مرزهای معنایی سند و تعیین «نوع بخش» (kind)
# ---------------------------------------------------------------------------

# هر anchor: (regex, kind, راهنمای بافتی که به مدل داده می‌شود)
SECTION_ANCHORS = [
    (r"عنوان\s*طرح\s*:", "operative_text",
     "توجه: در این بخش، عدد ابتدای خط (1، 2، 3...) شمارهٔ «ماده» است، نه «بند». "
     "متن‌های شروع‌شده با «تبصره» را داخل فیلد تبصرهٔ همان ماده قرار بده."),

    (r"نظر\s*اداره\s*کل\s*تدوین\s*قوانین", "review_tadvin",
     "توجه: در این بخش، عدد ابتدای خط شمارهٔ «بند» نظر کارشناسی است، نه «ماده»."),

    (r"نظر\s*اداره\s*کل\s*اسناد\s*و\s*تنقیح\s*قوانین", "review_asnad",
     "توجه: در این بخش، عدد ابتدای خط شمارهٔ «بند» نظر ادارهٔ اسناد است، نه «ماده»."),

    (r"دلایل\s*توجیهی|مقدمه", "intro_reasons",
     "توجه: در این بخش، عدد ابتدای خط شمارهٔ «بند» دلایل توجیهی مقدمه است، نه «ماده»."),

    (r"ضمیمه\s*نظر", "attachment",
     "توجه: این بخش «پیوست» سند است."),
]

# مرزهای ریزتر که هرگز نباید وسط‌شان بریده شود (حتی داخل یک section)
ATOMIC_BOUNDARY_PATTERN = re.compile(
    r"(?m)^(?:"
    r"باب\s*\S+|"
    r"فصل\s*\S+|"
    r"ماده\s*[\)\(]?\s*\d+|"
    r"تبصره\s*[\-–:]?\s*(?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|\d+)|"
    r"پیوست\b|"
    r"\d+\s"  # اعداد خام ابتدای خط (مواد/بندهای بدون کلمهٔ کلیدی در این سند)
    r")"
)


@dataclass
class Section:
    kind: str
    guidance: str
    text: str


def split_into_sections(text: str) -> list[Section]:
    """سند را بر اساس anchorهای معنایی به بخش‌های بزرگ (kind-دار) می‌شکند."""
    positions = []
    for pattern, kind, guidance in SECTION_ANCHORS:
        for m in re.finditer(pattern, text):
            positions.append((m.start(), kind, guidance))

    positions.sort(key=lambda x: x[0])

    if not positions or positions[0][0] > 0:
        # قسمت ابتدای سند قبل از اولین anchor (مثلاً شماره ثبت، کمیسیون‌ها)
        positions.insert(0, (0, "generic",
                              "توجه: این بخش شامل اطلاعات کلی سند (شماره ثبت، کمیسیون‌ها) است."))

    sections = []
    for i, (start, kind, guidance) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        sections.append(Section(kind=kind, guidance=guidance, text=text[start:end]))

    return sections


def split_into_atomic_units(section_text: str) -> list[str]:
    """یک بخش را به قطعات اتمی (هر قطعه از یک مرز تا مرز بعدی) می‌شکند."""
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
    """قطعات اتمی را در چانک‌هایی تا سقف max_size بسته‌بندی می‌کند؛
    هرگز یک قطعه را وسط نمی‌شکند، حتی اگر خودش از max_size بزرگ‌تر باشد."""
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


@dataclass
class PreparedChunk:
    text: str
    kind: str
    guidance: str


def build_chunks(text: str) -> list[PreparedChunk]:
    prepared = []
    for section in split_into_sections(text):
        units = split_into_atomic_units(section.text)
        for packed in pack_units_into_chunks(units, MAX_CHUNK_SIZE):
            prepared.append(PreparedChunk(text=packed, kind=section.kind, guidance=section.guidance))
    return prepared


# ---------------------------------------------------------------------------
# ۲) پرامپت سیستم (پایه + راهنمای بافتی هر چانک)
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

Hierarchy:

باب
└── فصل
    └── ماده
        ├── بند
        │   └── جزء
        └── تبصره

ONE-SHOT EXAMPLE:

INPUT:
باب دوم
احکام اجرایی

فصل اول
وظایف دستگاه‌های اجرایی

ماده ۶- دستگاه‌های اجرایی موظفند برنامه اجرایی خود را تهیه نمایند.

ماده ۷- برنامه اجرایی باید به تأیید مقام مسئول برسد.

OUTPUT:
{
  "باب": {
    "عنوان": "احکام اجرایی",
    "فصل": [
      {
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
            "تبصره": [],
            "ارجاع_داخلی": [],
            "ارجاع_بیرونی": []
          }
        ]
      }
    ]
  }
}

The input may be a chunk of a larger document.
Extract only the information present in the current chunk.
Do not invent missing context.

Return only valid JSON.
"""


def build_system_prompt(guidance: str) -> str:
    return BASE_SYSTEM_PROMPT + "\n\nCONTEXT GUIDANCE FOR THIS CHUNK:\n" + guidance


# ---------------------------------------------------------------------------
# ۳) فراخوانی مدل
# ---------------------------------------------------------------------------

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def call_model(chunk: PreparedChunk) -> dict:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": build_system_prompt(chunk.guidance)},
            {"role": "user", "content": chunk.text},
        ],
    )
    result = response.choices[0].message.content
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"raw_output": result, "error": "invalid_json"}


# ---------------------------------------------------------------------------
# ۴) ادغام خروجی همهٔ چانک‌ها در یک درخت واحد
# ---------------------------------------------------------------------------

def merge_results(chunk_outputs: list[dict], kinds: list[str]) -> dict:
    """
    نتایج چانک‌ها را بر اساس kind دسته‌بندی می‌کند تا هر بخش سند
    (متن مادهٔ واحد، نظر تدوین، نظر اسناد، مقدمه، پیوست، عمومی) در کلید
    مجزای خودش قرار گیرد و از قاطی‌شدن شماره‌گذاری‌های هم‌نام جلوگیری شود.
    داخل هر دسته، آیتم‌ها به ترتیب چانک الحاق می‌شوند (بدون ادعای merge
    عمیق‌تر از حد صحت داده‌های مدل).
    """
    merged: dict = {}
    for output, kind in zip(chunk_outputs, kinds):
        merged.setdefault(kind, []).append(output)
    return merged


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------

def main():
    text = Path(INPUT_FILE).read_text(encoding="utf-8")
    chunks = build_chunks(text)

    print(f"Document length: {len(text):,} characters")
    print(f"Total structure-aware chunks: {len(chunks)}")

    # پردازش موازی چانک‌ها به‌جای یکی‌یکی — بزرگ‌ترین اهرم کاهش زمان کل.
    # ترتیب نتایج با نگهداری ایندکس اصلی حفظ می‌شود، نه ترتیب اتمام.
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

            print(f"Finished {done_count}/{len(chunks)} "
                  f"(chunk {i + 1}, kind={kinds[i]})")

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