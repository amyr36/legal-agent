"""
Structure extraction for Persian legal text (structure-aware chunking + LLM).

Output: a flat list of records (one per legal unit) that can be written
as a JSONL file via `StructureResult.jsonl`.

What changed compared with the previous version
  - the parser reads JSONL (also tolerates a JSON array, code fences and
    <think> blocks); one bad line no longer discards the whole chunk
  - the prompt has no unused placeholder; the model no longer assigns
    `id` / `law_seq` / `law` (code does, so they are consistent)
  - every chunk gets context (law title, current باب/فصل, section kind)
  - section anchors only match at the start of a line
  - the bare-number boundary is much stricter (no dates / signature lines)
  - retries cover network errors and timeouts too, with backoff
  - failed chunks are kept as raw records so no text is silently lost

Settings used (app.core.config.settings):
  AVALAI_API_KEY      required
  AVALAI_BASE_URL     optional
  AVALAI_MODEL        optional fallback model
  STRUCTURE_MODEL     optional, overrides AVALAI_MODEL
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings


logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.avalai.ir/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"

# Soft cap for chunk size (characters). An atomic unit is never split.
MAX_CHUNK_SIZE = 1500

# Concurrent requests to the model. Lower it if you hit rate limits.
MAX_WORKERS = 4

MAX_ATTEMPTS = 3         # per chunk: retried on API errors and unusable output
REQUEST_TIMEOUT = 180    # seconds per model call
RETRY_BACKOFF = 2.0      # seconds, multiplied by the attempt number

# Drop lines that look like lists of MPs' signatures ("name- name- name-").
STRIP_SIGNATURE_LINES = True

# If a chunk fails completely, still emit its text as a "Raw" record.
KEEP_FAILED_AS_RAW = True


# ---------------------------------------------------------------------------
# 0) Text normalisation
# ---------------------------------------------------------------------------

_CHAR_MAP = str.maketrans({"ي": "ی", "ك": "ک"})
_INVISIBLE = re.compile(r"[\u200f\u200e\u202a-\u202e\ufeff\u0640]")  # RLM, LRM, tatweel...
_SIGNATURE_HINT = re.compile(r"\S-[ \t]+\S")


def normalize_text(text: str) -> str:
    text = text.translate(_CHAR_MAP)
    text = _INVISIBLE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if STRIP_SIGNATURE_LINES:
        kept, dropped = [], 0
        for line in text.split("\n"):
            if len(_SIGNATURE_HINT.findall(line)) >= 3:
                dropped += 1
                continue
            kept.append(line)
        if dropped:
            logger.info("Dropped %d signature-like lines", dropped)
        text = "\n".join(kept)

    return text.strip()


# ---------------------------------------------------------------------------
# 1) Semantic boundaries and section "kind"
# ---------------------------------------------------------------------------

# Persian text often has ZWNJ or no space between words, so anchors allow both.
_S = r"[\s\u200c]*"


def _anchor(*words: str) -> str:
    """Pattern matching the words at the START of a line only."""
    return r"(?m)^[ \t]*" + _S.join(words)


# Each anchor: (regex, kind, contextual guidance given to the model)
SECTION_ANCHORS = [
    (_anchor("عنوان", "طرح") + _S + ":", "operative_text",
     "توجه: در این بخش، عدد ابتدای خط (1، 2، 3...) شمارهٔ «ماده» است، نه «بند». "
     "متن‌های شروع‌شده با «تبصره» را داخل فیلد تبصرهٔ همان ماده قرار بده."),

    (_anchor("نظر", "اداره", "کل", "تدوین", "قوانین"), "review_tadvin",
     "توجه: در این بخش، عدد ابتدای خط شمارهٔ «بند» نظر کارشناسی است، نه «ماده»."),

    (_anchor("نظر", "اداره", "کل", "اسناد", "و", "تنقیح", "قوانین"), "review_asnad",
     "توجه: در این بخش، عدد ابتدای خط شمارهٔ «بند» نظر ادارهٔ اسناد است، نه «ماده»."),

    # «دلایل توجیهی» or a line that is just «مقدمه»
    (r"(?m)^[ \t]*(?:" + _S.join(["دلایل", "توجیهی"]) + r"|مقدمه[ \t]*:?[ \t]*$)",
     "intro_reasons",
     "توجه: در این بخش، عدد ابتدای خط شمارهٔ «بند» دلایل توجیهی مقدمه است، نه «ماده»."),

    (_anchor("ضمیمه", "نظر"), "attachment",
     "توجه: این بخش «پیوست» سند است."),
]

GENERIC_GUIDANCE = "توجه: این بخش شامل اطلاعات کلی سند (شماره ثبت، کمیسیون‌ها، مقدمهٔ تقدیم) است."

# Finer boundaries that must never be cut in the middle.
_KW_END = r"(?=[\s\d:\-–])"
ATOMIC_BOUNDARY_PATTERN = re.compile(
    r"(?m)^[ \t]*(?:"
    r"باب" + _KW_END + r"|"
    r"فصل" + _KW_END + r"|"
    r"ماده[ \t]*[\)\(]?[ \t]*\d+|"
    r"تبصره[ \t]*[\-–:]?[ \t]*(?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|\d+)|"
    r"پیوست" + _KW_END + r"|"
    # bare 1-3 digit numbers followed by text (clauses without a keyword);
    # excludes dates like "25 / 3 / 1389" and 4-digit years
    r"\d{1,3}(?:[ \t]*[-–.)][ \t]*|[ \t]+)(?=[^\s/\d])"
    r")"
)

_HEADING_BOOK = re.compile(r"(?m)^[ \t]*(باب(?=[\s\d:\-–])[^\n]*)")
_HEADING_CHAPTER = re.compile(r"(?m)^[ \t]*(فصل(?=[\s\d:\-–])[^\n]*)")


@dataclass
class Section:
    kind: str
    guidance: str
    text: str


def split_into_sections(text: str) -> list[Section]:
    """Split the document into large kind-tagged sections using the anchors."""
    positions = []
    for pattern, kind, guidance in SECTION_ANCHORS:
        for m in re.finditer(pattern, text):
            positions.append((m.start(), kind, guidance))

    positions.sort(key=lambda x: x[0])

    # Text before the first anchor (registration number, commissions...)
    if not positions or (positions[0][0] > 0 and text[: positions[0][0]].strip()):
        positions.insert(0, (0, "generic", GENERIC_GUIDANCE))
    elif positions[0][0] > 0:
        positions[0] = (0, positions[0][1], positions[0][2])

    sections = []
    for i, (start, kind, guidance) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk = text[start:end]
        if chunk.strip():
            sections.append(Section(kind=kind, guidance=guidance, text=chunk))

    return sections


def split_into_atomic_units(section_text: str) -> list[str]:
    """Split a section into atomic units (one boundary to the next)."""
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


def pack_units_into_units_chunks(units: list[str], max_size: int) -> list[list[str]]:
    """Pack atomic units into groups up to max_size; never splits a unit."""
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0

    for unit in units:
        if current and size + len(unit) > max_size:
            groups.append(current)
            current, size = [], 0
        current.append(unit)
        size += len(unit)

    if current:
        groups.append(current)

    return groups


@dataclass
class PreparedChunk:
    index: int
    text: str
    kind: str
    guidance: str
    law_title: Optional[str] = None
    book: Optional[str] = None
    chapter: Optional[str] = None


def extract_law_title(text: str) -> Optional[str]:
    m = re.search(r"(?m)^[ \t]*عنوان" + _S + r"طرح" + _S + r":[ \t]*(.+)$", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?m)^[ \t]*((?:طرح|لایحه)[ \t]+.+)$", text[:3000])
    return m.group(1).strip() if m else None


def build_chunks(text: str) -> list[PreparedChunk]:
    law_title = extract_law_title(text)
    prepared: list[PreparedChunk] = []

    for section in split_into_sections(text):
        units = split_into_atomic_units(section.text)
        book = chapter = None

        for group in pack_units_into_units_chunks(units, MAX_CHUNK_SIZE):
            # context at the START of this chunk
            chunk_book, chunk_chapter = book, chapter

            # update running heading state with headings inside this chunk
            for unit in group:
                mb = _HEADING_BOOK.match(unit)
                mc = _HEADING_CHAPTER.match(unit)
                if mb:
                    book, chapter = mb.group(1).strip(), None
                elif mc:
                    chapter = mc.group(1).strip()

            prepared.append(
                PreparedChunk(
                    index=len(prepared),
                    text="".join(group),
                    kind=section.kind,
                    guidance=section.guidance,
                    law_title=law_title,
                    book=chunk_book,
                    chapter=chunk_chapter,
                )
            )
    return prepared


# ---------------------------------------------------------------------------
# 2) Prompt
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = r"""
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


def build_system_prompt(guidance: str) -> str:
    return BASE_SYSTEM_PROMPT + "\nCONTEXT GUIDANCE FOR THIS CHUNK:\n" + guidance + "\n"


def build_user_message(chunk: PreparedChunk) -> str:
    return (
        "CONTEXT:\n"
        f"law: {chunk.law_title or 'unknown'}\n"
        f"section_kind: {chunk.kind}\n"
        f"current_book: {chunk.book or 'none'}\n"
        f"current_chapter: {chunk.chapter or 'none'}\n\n"
        "TEXT:\n" + chunk.text
    )


# ---------------------------------------------------------------------------
# 3) Model call + tolerant JSONL parsing
# ---------------------------------------------------------------------------

def _get_model_name() -> str:
    return (
        getattr(settings, "STRUCTURE_MODEL", None)
        or getattr(settings, "AVALAI_MODEL", None)
        or DEFAULT_MODEL
    )


def _make_client():
    # Imported lazily so the rest of the app starts without the package
    from openai import OpenAI

    api_key = getattr(settings, "AVALAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("AVALAI_API_KEY is not configured in settings")

    base_url = getattr(settings, "AVALAI_BASE_URL", None) or DEFAULT_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url)


_DECODER = json.JSONDecoder(strict=False)  # allows raw newlines inside strings


def parse_jsonl(raw: str) -> tuple[list[dict], int]:
    """Parse model output into records.

    Accepts JSONL, concatenated objects, or a JSON array; strips code
    fences and <think> blocks. Returns (records, skipped_fragments).
    A broken line only loses that line."""
    s = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    records: list[dict] = []
    skipped = 0
    pos, n = 0, len(s)

    while pos < n:
        while pos < n and (s[pos].isspace() or s[pos] == ","):
            pos += 1
        if pos >= n:
            break
        try:
            obj, end = _DECODER.raw_decode(s, pos)
        except json.JSONDecodeError:
            skipped += 1
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
        else:
            skipped += 1

    return records, skipped


@dataclass
class ChunkResult:
    records: list[dict] = field(default_factory=list)
    skipped: int = 0
    error: Optional[str] = None
    raw: str = ""


def call_model(client, chunk: PreparedChunk) -> ChunkResult:
    """Call the model for one chunk. Retries on API errors, timeouts and
    output that contains no usable record."""
    last_error = "unknown"
    raw = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=_get_model_name(),
                messages=[
                    {"role": "system", "content": build_system_prompt(chunk.guidance)},
                    {"role": "user", "content": build_user_message(chunk)},
                ],
                temperature=0,
                timeout=REQUEST_TIMEOUT,
            )
            raw = response.choices[0].message.content or ""
        except Exception as exc:  # network, timeout, rate limit...
            last_error = f"api_error: {exc}"
            logger.warning("Chunk %d attempt %d/%d API error: %s",
                           chunk.index, attempt, MAX_ATTEMPTS, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF * attempt)
            continue

        records, skipped = parse_jsonl(raw)
        if records:
            if skipped:
                logger.warning("Chunk %d: %d unparsable fragment(s) skipped", chunk.index, skipped)
            return ChunkResult(records=records, skipped=skipped, raw=raw)

        last_error = "invalid_output"
        logger.warning("Chunk %d attempt %d/%d: no usable JSONL", chunk.index, attempt, MAX_ATTEMPTS)

    return ChunkResult(error=last_error, raw=raw)


# ---------------------------------------------------------------------------
# 4) Post-processing: schema coercion, ids, context
# ---------------------------------------------------------------------------

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


def _default_breadcrumb(rec: dict) -> str:
    parts = [rec.get("law"), rec.get("book"), rec.get("chapter"), rec.get("subchapter")]
    label = " ".join(x for x in [rec.get("type"), rec.get("number_raw")] if x)
    parts.append(label or None)
    return " > ".join(p for p in parts if p)


def normalize_record(raw: dict, chunk: PreparedChunk) -> Optional[dict]:
    text = _to_str(raw.get("text"))
    if not text:
        return None

    rec = {
        "id": 0,  # assigned later
        "law_seq": 0,
        "category": _to_str(raw.get("category")),
        "law": _to_str(raw.get("law")) or chunk.law_title,
        "book": _to_str(raw.get("book")) or chunk.book,
        "chapter": _to_str(raw.get("chapter")) or chunk.chapter,
        "subchapter": _to_str(raw.get("subchapter")),
        "type": _to_str(raw.get("type")) or "Paragraph",
        "number_raw": _to_str(raw.get("number_raw")),
        "number": _to_int(raw.get("number")),
        "parent_number": _to_int(raw.get("parent_number")),
        "text": text,
        "breadcrumb": _to_str(raw.get("breadcrumb")),
    }
    if not rec["breadcrumb"]:
        rec["breadcrumb"] = _default_breadcrumb(rec)
    rec["section_kind"] = chunk.kind
    return rec


def _raw_record(chunk: PreparedChunk, error: str) -> dict:
    rec = {
        "id": 0,
        "law_seq": 0,
        "category": None,
        "law": chunk.law_title,
        "book": chunk.book,
        "chapter": chunk.chapter,
        "subchapter": None,
        "type": "Raw",
        "number_raw": None,
        "number": None,
        "parent_number": None,
        "text": chunk.text.strip(),
        "breadcrumb": chunk.law_title or "",
        "section_kind": chunk.kind,
        "parse_error": error,
    }
    return rec


# ---------------------------------------------------------------------------
# 5) Public entry point
# ---------------------------------------------------------------------------

@dataclass
class StructureResult:
    records: list[dict]       # final flat records, ids assigned
    data: dict                # {"meta": ..., "records": [...], "failed": [...]}
    total_chunks: int
    failed_chunks: int

    @property
    def jsonl(self) -> str:
        """One JSON object per line, Persian kept readable."""
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in self.records) + "\n"


def structure_text(text: str) -> StructureResult:
    """Convert extracted document text into structured records.

    Blocking and slow (one model call per chunk, run in parallel), so call
    it from a background job, never from inside a request handler."""
    text = normalize_text(text)
    chunks = build_chunks(text)
    if not chunks:
        raise ValueError("no text to structure")

    client = _make_client()
    results: list[Optional[ChunkResult]] = [None] * len(chunks)

    logger.info("Structuring: %d chars, %d chunks", len(text), len(chunks))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_index = {
            executor.submit(call_model, client, chunk): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            try:
                results[i] = future.result()
            except Exception as exc:
                logger.warning("Chunk %d/%d crashed: %s", i + 1, len(chunks), exc)
                results[i] = ChunkResult(error=f"crash: {exc}")

    # Assemble in document order and assign ids ourselves
    records: list[dict] = []
    failed: list[dict] = []

    for chunk, res in zip(chunks, results):
        if res.error or not res.records:
            error = res.error or "invalid_output"
            failed.append({
                "chunk": chunk.index,
                "kind": chunk.kind,
                "error": error,
                "raw_output": res.raw[:2000],
            })
            if KEEP_FAILED_AS_RAW:
                records.append(_raw_record(chunk, error))
            continue

        for raw in res.records:
            rec = normalize_record(raw, chunk)
            if rec:
                records.append(rec)

    for n, rec in enumerate(records, start=1):
        rec["id"] = n

    return StructureResult(
        records=records,
        data={
            "meta": {
                "model": _get_model_name(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "law": chunks[0].law_title,
                "total_chunks": len(chunks),
                "failed_chunks": len(failed),
                "total_records": len(records),
            },
            "records": records,
            "failed": failed,
        },
        total_chunks=len(chunks),
        failed_chunks=len(failed),
    )
