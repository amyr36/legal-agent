"""
Generic text extractor for (Persian) legal PDFs.

- Uses the native PDF text layer only (no OCR).
- Pages whose text looks garbled (legacy Persian font encodings) are
  reported in `suspect_pages` instead of being silently trusted.
- Repeated running headers/footers are stripped, but only from the
  first/last lines of a page, and never lines that look like legal
  headings (e.g. "ماده 12").

Output: an ExtractedDocument with the cleaned text plus a page offset
index, so a chunker can attribute any piece of text to its page(s).
"""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz  # PyMuPDF


CORRUPTION_THRESHOLD = 0.02            # share of suspicious words that flags a page
BOILERPLATE_MIN_PAGES = 4              # below this, repetition proves nothing
BOILERPLATE_MIN_PAGE_FRACTION = 0.5    # line must repeat on >= 50% of pages
BOILERPLATE_EDGE_LINES = 3             # only first/last N lines of a page
BOILERPLATE_MAX_LINE_LEN = 80          # headers/footers are short
MAX_PAGES = 1000                       # protects the server from huge PDFs


@dataclass
class PageInfo:
    page_num: int          # 1-indexed
    start_offset: int      # char offset into ExtractedDocument.text
    end_offset: int


@dataclass
class ExtractedDocument:
    text: str
    pages: list = field(default_factory=list)          # list[PageInfo]
    suspect_pages: list = field(default_factory=list)  # pages with garbled native text

    def page_for_offset(self, offset: int) -> int:
        """Return the 1-indexed page number containing a char offset."""
        for p in self.pages:
            if p.start_offset <= offset < p.end_offset:
                return p.page_num
        return self.pages[-1].page_num if self.pages else 1

    def page_range(self, start_offset: int, end_offset: int):
        return (
            self.page_for_offset(start_offset),
            self.page_for_offset(max(end_offset - 1, start_offset)),
        )

    def to_dict(self) -> dict:
        return {
            "char_count": len(self.text),
            "pages": [
                {"page": p.page_num, "start": p.start_offset, "end": p.end_offset}
                for p in self.pages
            ],
            "suspect_pages": self.suspect_pages,
        }


# ---------------------------------------------------------------------
# Corruption detection
# ---------------------------------------------------------------------

_SUSPICIOUS_PATTERNS = [
    r"[\u0600-\u06FF]{2,}[A-Za-z]{1,3}[\u0600-\u06FF]{2,}",  # persian+latin+persian glued
    r"[A-Za-z]{1,3}[\u0600-\u06FF]{2,}[A-Za-z]{1,3}",
    r"\uFFFD",
    r"[\uE000-\uF8FF]",  # private-use glyphs emitted by broken fonts
]
_SUSPICIOUS_RE = re.compile("|".join(_SUSPICIOUS_PATTERNS))


def corruption_score(text: str) -> float:
    words = text.split()
    if not words:
        return 1.0
    bad = sum(1 for w in words if _SUSPICIOUS_RE.search(w))
    return bad / len(words)


def is_corrupted(text: str) -> bool:
    return corruption_score(text) > CORRUPTION_THRESHOLD


# ---------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------

# Arabic letter variants -> Persian, tatweel removed, Persian/Arabic digits -> ASCII.
# ZWNJ (U+200C) is deliberately KEPT: it is part of correct Persian spelling.
_CHAR_MAP = {
    0x064A: "\u06CC",  # Arabic yeh -> Persian yeh
    0x0649: "\u06CC",  # alef maksura -> Persian yeh
    0x0643: "\u06A9",  # Arabic kaf -> Persian kaf
    0x06C0: "\u0647",  # heh with yeh above -> heh
    0x0629: "\u0647",  # teh marbuta -> heh
    0x0640: None,      # tatweel
}
for _i in range(10):
    _CHAR_MAP[0x06F0 + _i] = str(_i)  # Persian digits
    _CHAR_MAP[0x0660 + _i] = str(_i)  # Arabic-Indic digits
_TRANSLATE_TABLE = str.maketrans(_CHAR_MAP)


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANSLATE_TABLE)

    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)  # diacritics
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFD]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def fix_spacing(text: str) -> str:
    # Only spaces/tabs are touched, never newlines, so lines are not merged.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([،؛:؟!٪%)\]])", r"\1", text)
    text = re.sub(r"([(\[\{])[ \t]+", r"\1", text)
    text = re.sub(r"([،؛])(?=[آ-یA-Za-z])", r"\1 ", text)
    return text


def fix_pdf_hyphenation(text: str) -> str:
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            result.append("")
            continue
        if result and result[-1].endswith("-") and re.match(r"^[A-Za-z]", line):
            result[-1] = result[-1][:-1] + line
        else:
            result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------
# Repeated header/footer stripping
# ---------------------------------------------------------------------

# Lines that start like a legal heading are content, never boilerplate.
_PROTECTED_LINE_RE = re.compile(
    r"^\s*(ماده|فصل|بند|تبصره|مبحث|باب|Article|Section|Chapter)\b",
    re.IGNORECASE,
)


def _normalize_line(line: str) -> str:
    # Collapse digits so "page 8" and "page 9" count as the same line
    return re.sub(r"\d+", "#", line.strip())


def _is_candidate(line: str) -> bool:
    stripped = line.strip()
    return (
        bool(stripped)
        and len(stripped) <= BOILERPLATE_MAX_LINE_LEN
        and not _PROTECTED_LINE_RE.match(stripped)
    )


def _edge_indexes(n_lines: int) -> set:
    n = BOILERPLATE_EDGE_LINES
    return set(range(min(n_lines, n))) | set(range(max(0, n_lines - n), n_lines))


def strip_repeated_boilerplate(page_texts: list) -> list:
    n_pages = len(page_texts)
    if n_pages < BOILERPLATE_MIN_PAGES:
        return page_texts

    min_count = max(3, math.ceil(n_pages * BOILERPLATE_MIN_PAGE_FRACTION))

    counts = Counter()
    for text in page_texts:
        lines = text.splitlines()
        seen = set()
        for idx in _edge_indexes(len(lines)):
            line = lines[idx]
            if not _is_candidate(line):
                continue
            norm = _normalize_line(line)
            if norm not in seen:
                seen.add(norm)
                counts[norm] += 1

    boilerplate = {norm for norm, c in counts.items() if c >= min_count}
    if not boilerplate:
        return page_texts

    cleaned = []
    for text in page_texts:
        lines = text.splitlines()
        edges = _edge_indexes(len(lines))
        kept = [
            ln
            for i, ln in enumerate(lines)
            if not (
                i in edges
                and _is_candidate(ln)
                and _normalize_line(ln) in boilerplate
            )
        ]
        cleaned.append("\n".join(kept))

    return cleaned


# ---------------------------------------------------------------------
# Native (text-layer) extraction
# ---------------------------------------------------------------------

def _extract_page_native(page) -> str:
    words = page.get_text("words")
    if not words:
        return ""

    lines = {}
    for word in words:
        x0, y0, x1, y1, text, block_no, line_no, word_no = word
        if not text.strip():
            continue
        lines.setdefault((block_no, line_no), []).append(
            {"x0": x0, "y0": y0, "text": text.strip()}
        )

    ordered = sorted(
        lines.values(),
        key=lambda ln: (min(w["y0"] for w in ln), min(w["x0"] for w in ln)),
    )

    result = []
    for line in ordered:
        line.sort(key=lambda w: w["x0"], reverse=True)  # RTL
        result.append(" ".join(w["text"] for w in line))

    return "\n".join(result)


# ---------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------

def extract_pdf(path) -> ExtractedDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    raw_page_texts = []
    suspect_pages = []

    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("PDF is password protected")
        if pdf.page_count > MAX_PAGES:
            raise ValueError(f"PDF has more than {MAX_PAGES} pages")

        for i, page in enumerate(pdf, start=1):
            text = _extract_page_native(page)
            if text.strip() and is_corrupted(text):
                suspect_pages.append(i)
            raw_page_texts.append(text)

    cleaned_pages = strip_repeated_boilerplate(raw_page_texts)

    # Clean each page, then build text and offsets together so they always agree
    page_texts = []
    page_numbers = []
    for i, text in enumerate(cleaned_pages, start=1):
        text = fix_pdf_hyphenation(text)
        text = normalize_text(text)
        text = fix_spacing(text).strip()
        if text:
            page_texts.append(text)
            page_numbers.append(i)

    separator = "\n\n"
    page_infos = []
    offset = 0
    for num, text in zip(page_numbers, page_texts):
        page_infos.append(
            PageInfo(page_num=num, start_offset=offset, end_offset=offset + len(text))
        )
        offset += len(text) + len(separator)

    return ExtractedDocument(
        text=separator.join(page_texts),
        pages=page_infos,
        suspect_pages=suspect_pages,
    )


def extract_text(path) -> str:
    """Extract the cleaned text of a PDF."""
    return extract_pdf(path).text


# ---------------------------------------------------------------------
# Optional post-processing (not used by the upload service)
# ---------------------------------------------------------------------

def remove_emojis(text):
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text)


def remove_markdown(text):
    # Remove leading # from headings
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove **bold** markers
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    return text


def hazm_normalize_text(text):
    # Imported here so extraction works without hazm installed
    try:
        from hazm import Normalizer
    except ImportError:
        return text

    normalizer = Normalizer()

    text = remove_markdown(text)
    text = remove_emojis(text)
    text = normalizer.normalize(text)

    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{2,}", "\n\n", text)

    return text.strip()


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 3):
        print("Usage: python document_extraction.py <path-to-pdf> [output.txt]")
        raise SystemExit(1)

    doc = extract_pdf(sys.argv[1])
    output_path = sys.argv[2] if len(sys.argv) == 3 else "extracted_output.txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc.text)

    print(doc.text)
    if doc.suspect_pages:
        print(f"\n[Garbled text suspected on pages: {doc.suspect_pages}]", file=sys.stderr)
    print(f"Output saved to {output_path}")