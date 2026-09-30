import json
from pathlib import Path
from openai import OpenAI


API_KEY = "aa-UyS2fJjtEn41olAYj1e6f4cBzAiQyu7hi1S6QTm6OAk4DtD6"
BASE_URL = "https://api.avalai.ir/v1"
MODEL = "deepseek-v4.1-flash"

INPUT_FILE = "backend/tests/doc_rag/hormuz1.txt"
OUTPUT_FILE = "backend/tests/output_last/legal_document.json"

CHUNK_SIZE = 1500
OVERLAP = 100


SYSTEM_PROMPT = r"""
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

def create_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = OVERLAP
) -> list[str]:

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])

        if end >= len(text):
            break

        start = end - overlap

    return chunks


client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
)


# Read document
text = Path(INPUT_FILE).read_text(
    encoding="utf-8"
)


# Create chunks
chunks = create_chunks(
    text,
    CHUNK_SIZE
)

print(f"Document length: {len(text):,} characters")
print(f"Chunk size: {CHUNK_SIZE:,} characters")
print(f"Total chunks: {len(chunks)}")


results = []


# Process chunks
for i, chunk in enumerate(chunks, start=1):

    print(
        f"\nProcessing chunk {i}/{len(chunks)} "
        f"({len(chunk):,} characters)"
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": chunk,
            },
        ],
    )

    result = response.choices[0].message.content

    try:
        parsed_result = json.loads(result)

        results.append({
            "chunk": i,
            "data": parsed_result,
        })

    except json.JSONDecodeError:

        print(
            f"WARNING: Chunk {i} returned invalid JSON"
        )

        results.append({
            "chunk": i,
            "raw_output": result,
        })


# Save results
Path(OUTPUT_FILE).parent.mkdir(
    parents=True,
    exist_ok=True,
)

Path(OUTPUT_FILE).write_text(
    json.dumps(
        results,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)


print("\nDone.")
print(f"Output saved to: {OUTPUT_FILE}")