import json
from pathlib import Path
from openai import OpenAI


API_KEY = "aa-UyS2fJjtEn41olAYj1e6f4cBzAiQyu7hi1S6QTm6OAk4DtD6"
BASE_URL = "https://api.avalai.ir/v1"
MODEL = "deepseek-v4.1-flash"

INPUT_FILE = "backend/tests/doc_rag/hormuz1.txt"
OUTPUT_FILE = "backend/tests/output_last/legal_document.json"


SYSTEM_PROMPT = """
You are a Persian legal document structure extraction system.

Convert the given Persian legal text into JSON.

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

- Do not summarize.
- Do not interpret.
- Do not rewrite.
- Do not invent information.
- Preserve the original order.
- Preserve the original legal text as much as possible.
- Return only valid JSON.
"""


client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
)


text = Path(INPUT_FILE).read_text(
    encoding="utf-8"
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
            "content": text,
        },
    ],
)


result = response.choices[0].message.content


Path(OUTPUT_FILE).parent.mkdir(
    parents=True,
    exist_ok=True,
)


Path(OUTPUT_FILE).write_text(
    result,
    encoding="utf-8",
)


print(result)