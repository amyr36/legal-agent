"""
Structure extraction for Persian legal text (structure-aware chunking + LLM).

This is the former `text_to_json.py`, turned into an importable module:
  - no hardcoded API key: credentials come from app settings
  - no hardcoded input/output paths: `structure_text(text)` takes the text
    and returns the result; the caller decides where to store it
  - logging instead of print, one retry on invalid JSON

The chunking logic, section anchors, prompt and merge behaviour are
unchanged from your script.

Settings used (app.core.config.settings):
  AVALAI_API_KEY      required
  AVALAI_BASE_URL     optional, default https://api.avalai.ir/v1
  STRUCTURE_MODEL     optional, default deepseek-v4.1-flash
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import settings


logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = settings.AVALAI_BASE_URL
DEFAULT_MODEL = settings.AVALAI_MODEL

# Soft cap for chunk size (characters). An atomic unit is never split;
# a single unit larger than the cap is kept whole.
MAX_CHUNK_SIZE = 1500

# Concurrent requests to the model. Lower it if you hit rate limits.
MAX_WORKERS = 6

MAX_ATTEMPTS = 2        # per chunk, only retried on invalid JSON
REQUEST_TIMEOUT = 120   # seconds per model call


# ---------------------------------------------------------------------------
# 1) Semantic boundaries and section "kind"
# ---------------------------------------------------------------------------

# Each anchor: (regex, kind, contextual guidance given to the model)
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

# Finer boundaries that must never be cut in the middle
ATOMIC_BOUNDARY_PATTERN = re.compile(
    r"(?m)^(?:"
    r"باب\s*\S+|"
    r"فصل\s*\S+|"
    r"ماده\s*[\)\(]?\s*\d+|"
    r"تبصره\s*[\-–:]?\s*(?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|\d+)|"
    r"پیوست\b|"
    r"\d+\s"  # bare leading numbers (articles/clauses without a keyword)
    r")"
)


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

    if not positions or positions[0][0] > 0:
        # Text before the first anchor (registration number, commissions...)
        positions.insert(0, (0, "generic",
                              "توجه: این بخش شامل اطلاعات کلی سند (شماره ثبت، کمیسیون‌ها) است."))

    sections = []
    for i, (start, kind, guidance) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        sections.append(Section(kind=kind, guidance=guidance, text=text[start:end]))

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


def pack_units_into_chunks(units: list[str], max_size: int) -> list[str]:
    """Pack atomic units into chunks up to max_size; never splits a unit."""
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
            prepared.append(
                PreparedChunk(text=packed, kind=section.kind, guidance=section.guidance)
            )
    return prepared


# ---------------------------------------------------------------------------
# 2) System prompt (base + per-chunk contextual guidance)
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = r"""
You are an expert legal document parser.

Task:
Convert the provided legal, regulatory, administrative, policy, contract, directive, circular, guideline, or legislative document into structured JSONL records.

Requirements:

1. Preserve the document hierarchy.
   Possible hierarchy levels may include:
   - Title
   - Part
   - Book
   - Section
   - Chapter
   - Subchapter
   - Article
   - Clause
   - Paragraph
   - Note
   - Appendix
   - Amendment
   - Any equivalent legal structure

2. Generate one JSON object per logical legal unit.

3. For each unit extract:

{
  "id": integer,
  "law_seq": integer,
  "category": string|null,
  "law": string|null,
  "book": string|null,
  "chapter": string|null,
  "subchapter": string|null,
  "type": string,
  "number_raw": string|null,
  "number": integer|null,
  "parent_number": integer|null,
  "text": string,
  "breadcrumb": string
}

Field Rules:

- id: sequential record id.
- law_seq: document sequence number (start from 0 if unknown).
- category: high-level category if explicitly available.
- law: law or regulation name if identifiable.
- book/chapter/subchapter: nearest hierarchical titles.
- type: legal unit type.
- number_raw: original numbering exactly as written.
- number: normalized numeric value when possible.
- parent_number: parent article/clause number when applicable.
- text: full content of the legal unit.
- breadcrumb: full hierarchy path from document title to current node.

Hierarchy Rules:

- Detect hierarchical relationships automatically.
- Notes, clauses, subclauses, appendices and amendments must remain attached to their parent unit.
- Do not merge unrelated legal units.
- Preserve legal wording exactly.
- Do not summarize.
- Do not rewrite.
- Do not interpret.

Output Rules:

- Return ONLY valid JSONL.
- One JSON object per line.
- No markdown.
- No explanations.
- No comments.
- No extra text.

Example:

{"id":1,"law_seq":0,"category":null,"law":null,"book":"Document Title","chapter":null,"subchapter":null,"type":"Title","number_raw":null,"number":null,"parent_number":null,"text":"Document Title","breadcrumb":"Document Title"}

Document:
{{LEGAL_DOCUMENT_TEXT}}

Return only valid JSONL.
"""


def build_system_prompt(guidance: str) -> str:
    return BASE_SYSTEM_PROMPT + "\n\nCONTEXT GUIDANCE FOR THIS CHUNK:\n" + guidance


# ---------------------------------------------------------------------------
# 3) Model call
# ---------------------------------------------------------------------------

def _get_model_name() -> str:
    return getattr(settings, "STRUCTURE_MODEL", None) or DEFAULT_MODEL


def _make_client():
    # Imported lazily so the rest of the app starts without the package
    from openai import OpenAI

    api_key = getattr(settings, "AVALAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("AVALAI_API_KEY is not configured in settings")

    base_url = getattr(settings, "AVALAI_BASE_URL", None) or DEFAULT_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url)


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip()
    # Some models wrap JSON in a Markdown fence despite instructions
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    return json.loads(cleaned)


def call_model(client, chunk: PreparedChunk) -> dict:
    """Return the parsed JSON for one chunk. Network/API errors propagate
    (the caller records them); invalid JSON is retried once."""
    raw = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=_get_model_name(),
            messages=[
                {"role": "system", "content": build_system_prompt(chunk.guidance)},
                {"role": "user", "content": chunk.text},
            ],
            timeout=REQUEST_TIMEOUT,
        )
        raw = response.choices[0].message.content or ""
        try:
            return _parse_json(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from model (attempt %d/%d)", attempt, MAX_ATTEMPTS)

    return {"raw_output": raw, "error": "invalid_json"}


# ---------------------------------------------------------------------------
# 4) Merge chunk outputs
# ---------------------------------------------------------------------------

def merge_results(chunk_outputs: list[dict], kinds: list[str]) -> dict:
    """
    Group chunk outputs by section kind so numbering from different parts
    of the document (operative text, expert reviews, introduction,
    attachment) never mixes. Inside each kind, outputs stay in chunk order.
    """
    merged: dict = {}
    for output, kind in zip(chunk_outputs, kinds):
        merged.setdefault(kind, []).append(output)
    return merged


# ---------------------------------------------------------------------------
# 5) Public entry point
# ---------------------------------------------------------------------------

@dataclass
class StructureResult:
    data: dict            # the full JSON document to store: {"meta": ..., "data": ...}
    total_chunks: int
    failed_chunks: int


def _is_failed(output: dict) -> bool:
    return isinstance(output, dict) and "error" in output


def structure_text(text: str) -> StructureResult:
    """Convert extracted document text into structured JSON.

    Blocking and slow (one model call per chunk, run in parallel), so call
    it from a background job, never from inside a request handler."""
    chunks = build_chunks(text)
    if not chunks:
        raise ValueError("no text to structure")

    client = _make_client()
    kinds = [chunk.kind for chunk in chunks]
    outputs: list = [None] * len(chunks)

    logger.info("Structuring: %d chars, %d chunks", len(text), len(chunks))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_index = {
            executor.submit(call_model, client, chunk): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            try:
                outputs[i] = future.result()
            except Exception as exc:
                logger.warning("Chunk %d/%d failed: %s", i + 1, len(chunks), exc)
                outputs[i] = {"error": str(exc)}

    failed = sum(1 for o in outputs if _is_failed(o))

    return StructureResult(
        data={
            "meta": {
                "model": _get_model_name(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_chunks": len(chunks),
                "failed_chunks": failed,
            },
            "data": merge_results(outputs, kinds),
        },
        total_chunks=len(chunks),
        failed_chunks=failed,
    )