from pathlib import Path
from openai import OpenAI


API_KEY = "aa-UyS2fJjtEn41olAYj1e6f4cBzAiQyu7hi1S6QTm6OAk4DtD6"
BASE_URL = "https://api.avalai.ir/v1"
MODEL = "deepseek-v4.1-flash"

INPUT_FILE = "backend/tests/doc_rag/hormuz1.txt"
OUTPUT_FILE = "backend/tests/output_last/legal_document.json"


SYSTEM_PROMPT = r"""
You are an expert parser of Persian legal documents (bills, reports, expert opinions).

Task:
Convert the text you receive into JSONL: one JSON object per logical legal unit.
The text was extracted from a PDF and may be noisy (odd spacing, stray dashes,
checkbox options like "است / نیست"). Keep the wording exactly as it appears.

Each object has exactly these fields:

{"type": string, "number_raw": string|null, "number": integer|null,
 "parent_number": integer|null, "book": string|null, "chapter": string|null,
 "subchapter": string|null, "text": string, "breadcrumb": string}

Field rules:
- type: kind of unit, e.g. Title, Preamble, Article, Clause, Subclause, Note, Appendix, Paragraph, Signature.
- number_raw: the numbering exactly as written (e.g. "1", "ماده 3", "الف"), else null.
- number: the integer value of the numbering when possible, else null.
- parent_number: number of the parent article/clause when this unit belongs to one (notes, subclauses), else null.
- book / chapter / subchapter: nearest headings. Use CONTEXT if the chunk starts inside a chapter.
- text: the full text of the unit, unchanged.
- breadcrumb: path from the document title down to this unit, joined with " > ".

Rules:
- Notes (تبصره), clauses and subclauses stay attached to their parent via parent_number.
- Do not merge unrelated units. Do not summarize, rewrite, translate or interpret.
- Do not invent text that is not in the input.
- Do not output id or law_seq fields.

Output format (strict):
- ONLY JSONL: one JSON object per line, no array brackets, no markdown fences, no comments, no extra text.
- Escape newlines inside "text" as \n so each object stays on a single line.
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