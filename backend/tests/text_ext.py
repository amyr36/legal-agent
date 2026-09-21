"""
Generic text extractor for (Persian) legal PDFs.

Goals:
- Work reasonably well on *any* PDF, not just one specific document.
- Don't try to be perfect: prefer the fast native text layer, and only
  fall back to OCR on pages where the native layer looks broken
  (common with old/legacy Persian fonts whose encoding confuses
  extraction libraries).
- Strip repeated headers/footers automatically (by detecting lines
  that repeat across most pages), instead of hardcoding regexes for
  one specific source.

Output: an ExtractedDocument with the full cleaned text plus a page
offset index, so a downstream chunker can attribute any chunk of text
back to the page(s) it came from (useful for legal citations).
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
from collections import Counter

import fitz  # PyMuPDF

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


OCR_LANG = "fas"                 # Persian Tesseract trained data. Use "fas+ara+eng" for mixed documents.
OCR_DPI = 300
CORRUPTION_THRESHOLD = 0.02       # fraction of suspicious "words" that triggers OCR fallback
BOILERPLATE_MIN_PAGE_FRACTION = 0.4  # a line repeating on >=40% of pages is treated as header/footer


@dataclass
class PageInfo:
    page_num: int          # 1-indexed
    start_offset: int       # char offset into ExtractedDocument.text
    end_offset: int


@dataclass
class ExtractedDocument:
    text: str
    pages: list = field(default_factory=list)  # list[PageInfo]
    ocr_pages: list = field(default_factory=list)  # page numbers where OCR fallback was used

    def page_for_offset(self, offset: int) -> int:
        """Return the 1-indexed page number containing a given char offset."""
        for p in self.pages:
            if p.start_offset <= offset < p.end_offset:
                return p.page_num
        return self.pages[-1].page_num if self.pages else 1

    def page_range(self, start_offset: int, end_offset: int):
        return self.page_for_offset(start_offset), self.page_for_offset(max(end_offset - 1, start_offset))


# ---------------------------------------------------------------------
# Corruption detection (generic, not tied to one document)
# ---------------------------------------------------------------------

_SUSPICIOUS_PATTERNS = [
    r"[\u0600-\u06FF]{2,}[A-Za-z]{1,3}[\u0600-\u06FF]{2,}",  # persian+latin+persian glued together
    r"[A-Za-z]{1,3}[\u0600-\u06FF]{2,}[A-Za-z]{1,3}",
    r"\uFFFD",
    r"[\uE000-\uF8FF]",  # private-use-area glyphs some broken fonts emit
]
_SUSPICIOUS_RE = re.compile("|".join(_SUSPICIOUS_PATTERNS))


def corruption_score(text: str) -> float:
    if not text.strip():
        return 1.0
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

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)

    replacements = {
        "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ـ": "",
        "‌": " ",  # ZWNJ -> space (safer for embeddings/search than deleting it)
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)          # diacritics
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFD]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def fix_spacing(text: str) -> str:
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\s+([،؛:؟!٪%)\]])", r"\1", text)
    text = re.sub(r"([(\[\{])\s+", r"\1", text)
    text = re.sub(r"([،؛])(?=[آ-یA-Za-z])", r"\1 ", text)
    return text


def fix_pdf_hyphenation(text: str) -> str:
    lines = text.splitlines()
    result = []
    for line in lines:
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
# Generic repeated-header/footer stripping
# ---------------------------------------------------------------------

def strip_repeated_boilerplate(page_texts: list) -> list:
    """
    Detect lines that repeat (near-)verbatim across a large fraction of
    pages - typically running headers, footers, page numbers, printed
    URLs/timestamps - and drop them. Works for any document, no
    document-specific regex needed.
    """

    if len(page_texts) < 3:
        return page_texts  # not enough pages to tell "repeated" from "coincidence"

    def normalize_line(line: str) -> str:
        line = line.strip()
        line = re.sub(r"\d+", "#", line)  # collapse page numbers / dates so "8 of 1" == "8 of 2"
        return line

    line_page_counts = Counter()
    for text in page_texts:
        seen_this_page = set()
        for line in text.splitlines():
            norm = normalize_line(line)
            if norm and norm not in seen_this_page:
                line_page_counts[norm] += 1
                seen_this_page.add(norm)

    n_pages = len(page_texts)
    boilerplate = {
        norm for norm, count in line_page_counts.items()
        if count / n_pages >= BOILERPLATE_MIN_PAGE_FRACTION
    }

    cleaned_pages = []
    for text in page_texts:
        kept = [ln for ln in text.splitlines() if normalize_line(ln) not in boilerplate]
        cleaned_pages.append("\n".join(kept))

    return cleaned_pages


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
        key = (block_no, line_no)
        lines.setdefault(key, []).append(
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


def _extract_page_ocr(page) -> str:
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "OCR fallback needs pytesseract + Pillow "
            "(pip install pytesseract pillow) and a Tesseract binary "
            "with the 'fas' language pack installed."
        )
    zoom = OCR_DPI / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(img, lang=OCR_LANG, config="--psm 6").strip()


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------

def extract_pdf(path) -> ExtractedDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    raw_page_texts = []
    ocr_pages = []

    with fitz.open(path) as document:
        for i, page in enumerate(document, start=1):
            native_text = _extract_page_native(page)

            if is_corrupted(native_text) and OCR_AVAILABLE:
                try:
                    text = _extract_page_ocr(page)
                    ocr_pages.append(i)
                except Exception:
                    text = native_text
            else:
                text = native_text

            raw_page_texts.append(text)

    cleaned_pages = strip_repeated_boilerplate(raw_page_texts)

    # Clean + build the offset index in one pass
    full_text_parts = []
    page_infos = []
    offset = 0

    for i, text in enumerate(cleaned_pages, start=1):
        text = fix_pdf_hyphenation(text)
        text = normalize_text(text)
        text = fix_spacing(text)

        if not text:
            continue

        start = offset
        full_text_parts.append(text)
        offset += len(text)
        page_infos.append(PageInfo(page_num=i, start_offset=start, end_offset=offset))

        # separator between pages (kept out of any page's own offset range)
        full_text_parts.append("\n\n")
        offset += 2

    return ExtractedDocument(
        text="".join(full_text_parts).strip(),
        pages=page_infos,
        ocr_pages=ocr_pages,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python extractor.py <path-to-pdf>")
        raise SystemExit(1)

    doc = extract_pdf(sys.argv[1])
    print(doc.text)
    if doc.ocr_pages:
        print(f"\n[OCR fallback used on pages: {doc.ocr_pages}]", file=sys.stderr)