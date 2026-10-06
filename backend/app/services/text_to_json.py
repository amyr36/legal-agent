"""
Structure extraction for Persian bills (single LLM call, no chunking).

Used by `document_service.run_structure_extraction`:
`structure_text(text)` takes the extracted text and returns a
`StructureResult`. The output is JSONL (one JSON object per line):

    result = structure_text(text)
    result.write_jsonl("structured.jsonl")

Speed: the model does NOT rewrite the text. The input is sent as numbered
lines ("[12] ...") and the model only returns, for every part (title,
preamble, each article), the first and last line number. The program cuts
the text out of the input itself. The model output is therefore a few short
JSON lines instead of the whole bill, and the text in every record is
exactly the text of the input (nothing can be dropped or reworded).

One record per top-level article of the bill (with its clauses, notes and
quoted text inside), plus one title record and one preamble record.
`id` and `doc_title` are added by code.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI

from app.core.config import settings


logger = logging.getLogger(__name__)

API_KEY = settings.AVALAI_API_KEY
BASE_URL = "https://api.avalai.ir/v1"
MODEL = "deepseek-v4.1-flash"

REQUEST_TIMEOUT = 300   # seconds per model call
MAX_ATTEMPTS = 2        # retried on API errors and on output with no usable record
RETRY_BACKOFF = 3.0     # seconds, multiplied by the attempt number

VALID_KINDS = {"title", "preamble", "article"}


SYSTEM_PROMPT = r"""
You are a parser for Persian parliamentary bills (طرح / لایحه).
The input is text extracted from a PDF, one line per row. Every row starts with its
line number in square brackets, for example: "[12] متن خط". The text may be noisy:
misplaced parentheses and dashes, words out of place, checkbox options such as
"است / نیست".

Goal: LOCATE the parts listed below, so that each article can later be compared with
articles of another bill. You do NOT copy any text. For every part you return only
the line number where it starts and the line number where it ends (both inclusive,
numbers taken from the brackets). The program cuts the text out by itself.

OUTPUT RECORDS (in document order; line ranges must not overlap)
1. Exactly one record with kind "title": the line(s) holding the title of the bill
   (the line that starts with «عنوان طرح:», possibly continuing on the next line,
   or otherwise the bill title).
2. At most one record with kind "preamble": the justification section
   (مقدمه / دلایل توجیهی). Start at the first line of its body, not at its heading,
   and end before the signatory names.
3. One record with kind "article" per TOP-LEVEL article of the bill
   (ماده 1, ماده 2, ...), in order.

ARTICLE RULES
- An article starts at the line that contains its "ماده N" and ends at the last line
  that belongs to it, just before the next top-level article, the next chapter
  heading, or the end of the bill body. Its range covers everything inside: the
  opening sentence, quoted replacement text «...», numbered clauses (بند), notes
  (تبصره) and any article nested inside a quotation.
- NEVER split one article into several records. Never create a record for a clause,
  a note, or a nested article.
- Top-level articles are numbered consecutively (1, 2, 3, ...). A number such as
  "ماده 22", "ماده 22 مکرر", "تبصره 1" or "1 _ ..." that appears inside a quotation
  «...» or after a sentence like "به شرح زیر اصلاح میشود" / "الحاق میگردد" belongs
  to the law being amended: it stays inside the enclosing top-level article.
- Chapter headings (فصل ...) are not part of any article range. For each article give
  in "chapter_line" the line number of the nearest preceding chapter heading;
  null if the bill has no chapters.
- "number": integer value of the top-level article number. "number_raw": as written
  (e.g. "ماده 4"). Keep numbers as they are even if they skip or repeat.
- "amends_law" / "amends_article": if the article amends, adds to or repeals a
  provision of ANOTHER law, give that law and that article exactly as written in the
  article's own sentence (e.g. "قانون حمایت خانواده" and "ماده (22)"). If it only
  refers to a part of the amended article, give the article (e.g. "ماده (1130)").
  If the article is an ordinary provision of the bill itself, both are null.
  Do not guess.

WHAT TO LEAVE OUT (no record, and inside no range)
- Before the body: registration number (شماره ثبت), term/session line, "عادی",
  referral commissions (کمیسیون های ارجاعی), «معاونت قوانین», «باسمه تعالی»,
  the letter to «ریاست محترم مجلس», lists of signatories and their names.
- The bill body ends where the cover letter addressed to
  «هیأت رئیسه محترم مجلس شورای اسلامی» begins. Everything from that letter to the
  end of the input is ignored: the opinions of the legal offices
  (نظر اداره‌کل تدوین قوانین / اسناد و تنقیح قوانین), forms with checkbox options,
  signatures of officials, attachments (ضمیمه) and lists of related laws.

FIELDS (every record has all of them)
{"kind": "title"|"preamble"|"article",
 "number": integer|null, "number_raw": string|null,
 "start_line": integer, "end_line": integer,
 "chapter_line": integer|null,
 "amends_law": string|null, "amends_article": string|null}
For title and preamble records number, number_raw, chapter_line, amends_law and
amends_article are null.

EXAMPLE (invented)
{"kind":"title","number":null,"number_raw":null,"start_line":6,"end_line":7,"chapter_line":null,"amends_law":null,"amends_article":null}
{"kind":"article","number":2,"number_raw":"ماده 2","start_line":24,"end_line":31,"chapter_line":19,"amends_law":"قانون الف","amends_article":"ماده (5)"}

OUTPUT FORMAT (strict)
- ONLY JSONL: one JSON object per line, no array brackets, no markdown fences, no
  comments, no extra text.
- Do not output any text of the bill and do not output id fields.
"""


# ---------------------------------------------------------------------------
# Input numbering, parsing and normalisation
# ---------------------------------------------------------------------------

def _number_lines(text: str) -> tuple[list[str], str]:
    """Split the text into non-empty lines and build the numbered prompt input."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    numbered = "\n".join(f"[{i}] {ln}" for i, ln in enumerate(lines, start=1))
    return lines, numbered


_DECODER = json.JSONDecoder(strict=False)  # tolerate raw newlines inside strings


def _parse_output(raw: str) -> list[dict]:
    """Turn the model answer (JSONL, concatenated objects or a JSON array)
    into a list of dicts. A broken line only loses that line."""
    s = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    records: list[dict] = []
    pos, n = 0, len(s)
    while pos < n:
        while pos < n and (s[pos].isspace() or s[pos] == ","):
            pos += 1
        if pos >= n:
            break
        try:
            obj, end = _DECODER.raw_decode(s, pos)
        except json.JSONDecodeError:
            nxt = s.find("\n{", pos + 1)
            if nxt == -1:
                break
            pos = nxt + 1
            continue
        pos = end
        if isinstance(obj, dict):
            records.append(obj)
        elif isinstance(obj, list):
            records.extend(o for o in obj if isinstance(o, dict))
    return records


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _to_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.translate(_DIGITS).strip()
        if re.fullmatch(r"\d+", v):
            return int(v)
    return None


def _to_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


_TITLE_LABEL = re.compile(r"^\s*عنوان\s*طرح\s*:\s*")


def _build_record(raw: dict, lines: list[str]) -> Optional[tuple[dict, int, int]]:
    """Cut the text of one record out of the input lines.
    Returns (record, start_line, end_line) or None if the range is invalid."""
    kind = (_to_str(raw.get("kind")) or "").lower()
    start = _to_int(raw.get("start_line"))
    end = _to_int(raw.get("end_line"))
    if kind not in VALID_KINDS or start is None or end is None:
        return None
    if not (1 <= start <= end <= len(lines)):
        return None

    chunk = lines[start - 1:end]
    if kind == "title":
        text = _TITLE_LABEL.sub("", " ".join(chunk)).strip()
    else:
        text = "\n".join(chunk)
    if not text:
        return None

    chapter = None
    chapter_line = _to_int(raw.get("chapter_line"))
    if kind == "article" and chapter_line is not None and 1 <= chapter_line <= len(lines):
        chapter = lines[chapter_line - 1]

    record = {
        "kind": kind,
        "number": _to_int(raw.get("number")),
        "number_raw": _to_str(raw.get("number_raw")),
        "chapter": chapter,
        "amends_law": _to_str(raw.get("amends_law")),
        "amends_article": _to_str(raw.get("amends_article")),
        "text": text,
    }
    return record, start, end


# ---------------------------------------------------------------------------
# Checks (warnings only, stored in meta)
# ---------------------------------------------------------------------------

def _check(records: list[dict], spans: list[tuple[int, int]]) -> dict:
    """Cheap sanity checks. They never fail the run; they are reported in meta."""
    overlapping = [
        records[i]["id"]
        for i in range(1, len(records))
        if spans[i][0] <= spans[i - 1][1]
    ]

    numbers = [r["number"] for r in records
               if r["kind"] == "article" and r["number"] is not None]
    missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers)) if numbers else []
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})

    return {
        "overlapping_ids": overlapping,
        "missing_article_numbers": missing,
        "duplicate_article_numbers": duplicates,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@dataclass
class StructureResult:
    jsonl: str            # the output file content: one JSON object per line
    records: list[dict]   # the same records as dicts
    meta: dict            # run info and checks (not part of the JSONL file)
    total_chunks: int
    failed_chunks: int

    @property
    def data(self) -> str:
        """JSONL text. Kept so code that stores `result.data` keeps working."""
        return self.jsonl

    def write_jsonl(self, path) -> None:
        Path(path).write_text(self.jsonl, encoding="utf-8")


def structure_text(text: str) -> StructureResult:
    """Convert extracted document text into JSONL records (one model call)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("no text to structure")
    if not API_KEY:
        raise RuntimeError("AVALAI_API_KEY is not configured in settings")

    lines, numbered = _number_lines(text)
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    raw_records: list[dict] = []
    truncated = False
    error: Optional[str] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": numbered},
                ],
                temperature=0,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as exc:  # network, timeout, rate limit, quota...
            error = f"api_error: {exc}"
            logger.warning("Structure call %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF * attempt)
            continue

        usage = getattr(response, "usage", None)
        logger.info(
            "Structure call took %.1fs (completion_tokens=%s)",
            time.monotonic() - started,
            getattr(usage, "completion_tokens", "?"),
        )

        choice = response.choices[0]
        truncated = choice.finish_reason == "length"
        raw_records = _parse_output(choice.message.content or "")
        if raw_records:
            error = None
            break

        error = "no_usable_output"
        logger.warning("Structure call %d/%d: no usable JSONL", attempt, MAX_ATTEMPTS)

    built = [b for b in (_build_record(x, lines) for x in raw_records) if b]
    invalid = len(raw_records) - len(built)

    cleaned = [b[0] for b in built]
    spans = [(b[1], b[2]) for b in built]
    doc_title = next((r["text"] for r in cleaned if r["kind"] == "title"), None)
    records = [
        {"id": i, "doc_title": doc_title, **r}
        for i, r in enumerate(cleaned, start=1)
    ]

    checks = _check(records, spans)
    if truncated:
        logger.warning("Model output was cut off (finish_reason=length); result is partial")
    if invalid:
        logger.warning("%d record(s) dropped: invalid line range", invalid)
    if checks["overlapping_ids"]:
        logger.warning("Records with overlapping line ranges: %s", checks["overlapping_ids"])
    if checks["missing_article_numbers"]:
        logger.warning("Missing article numbers: %s", checks["missing_article_numbers"])

    failed = 1 if (not records or truncated) else 0
    jsonl = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)

    return StructureResult(
        jsonl=jsonl,
        records=records,
        meta={
            "model": MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": len(records),
            "truncated": truncated,
            "error": error,
            "invalid_records": invalid,
            **checks,
        },
        total_chunks=1,
        failed_chunks=failed,
    )