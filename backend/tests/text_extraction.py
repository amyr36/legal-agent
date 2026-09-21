"""
Improved Persian PDF text extraction.

Key change vs. the original script:
------------------------------------
Many Persian/Arabic PDFs (especially exports from Word/InDesign, or
scanned-then-reflowed government documents like this one) embed a
font whose ToUnicode CMap does NOT correctly map certain mandatory
ligatures - most commonly "لا" (lam + alef). When that happens, no
amount of post-processing on the extracted text can recover the
missing letters, because they were never extracted correctly in the
first place (PyMuPDF returns nothing, a private-use-area codepoint,
or garbage for that glyph).

Symptoms you'll see in the raw PyMuPDF output:
    "انقلاب"  ->  "انق ب"      (لا silently dropped)
    "اسلامی"  ->  "اس می"      (لا silently dropped)
    "سیاسی"   ->  "سیاjt"      (a glyph mapped to a stray Latin char)

The fix: detect when a page's extracted text looks corrupted, and
fall back to OCR (Tesseract, Persian language pack) on a rendered
image of that page. OCR reads the actual glyph shapes, so it isn't
affected by a broken CMap.

Requirements for the OCR fallback:
    pip install pytesseract pillow
    # + Tesseract binary with the Persian ("fas") trained data, e.g.:
    #   Debian/Ubuntu: sudo apt-get install tesseract-ocr tesseract-ocr-fas
    #   macOS (brew):  brew install tesseract tesseract-lang
If Tesseract/fas isn't installed, the script still runs - it just
keeps the (possibly corrupted) native text layer and warns you.
"""

from pathlib import Path
import re
import unicodedata

import fitz

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


TEST_DIR = Path(__file__).parent
PDF_FILE = TEST_DIR / "documents" / "test.pdf"
OUTPUT_DIR = TEST_DIR / "output"

OUTPUT_DIR.mkdir(exist_ok=True)

OCR_LANG = "fas"          # Persian trained data for Tesseract
OCR_DPI = 300             # higher DPI = better OCR accuracy, slower
CORRUPTION_THRESHOLD = 0.015  # fraction of "suspicious" chars/words that triggers OCR fallback


# ---------------------------------------------------------------------
# Corruption detection
# ---------------------------------------------------------------------

# A Persian/Arabic word run broken up by a stray Latin letter in the
# middle (e.g. "سیاjt", "jYمایه") is the clearest fingerprint of a
# broken ligature/cmap. Also flag the Unicode replacement character
# and Private Use Area codepoints, which some broken fonts emit.
_SUSPICIOUS_PATTERNS = [
    r"[\u0600-\u06FF]{2,}[A-Za-z]{1,3}[\u0600-\u06FF]{2,}",  # فا+lat+فا
    r"[A-Za-z]{1,3}[\u0600-\u06FF]{2,}[A-Za-z]{1,3}",         # lat+فا+lat
    r"\uFFFD",                                                # replacement char
    r"[\uE000-\uF8FF]",                                       # private-use area glyphs
]
_SUSPICIOUS_RE = re.compile("|".join(_SUSPICIOUS_PATTERNS))


def corruption_score(text: str) -> float:
    """
    Rough fraction of "words" in text that look corrupted.
    0.0 = looks clean, higher = more likely broken font/cmap extraction.
    """

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
    """
    Persian/Arabic Unicode normalization.
    """

    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ـ": "",   # tatweel/kashida
        "‌": " ",  # ZWNJ -> normal space (safer for search/embedding than dropping it)
        # Eastern Arabic-Indic digits -> ASCII (comment out if you want to keep Persian digits)
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove Arabic diacritics
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)

    # Remove control characters and the Unicode replacement char
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFD]", "", text)

    # Normalize spaces
    text = re.sub(r"[ \t]+", " ", text)

    # Normalize excessive empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def fix_spacing(text: str) -> str:
    """
    Fix obvious spacing around punctuation.
    """

    text = re.sub(r" {2,}", " ", text)

    text = re.sub(r"\s+([،؛:؟!٪%)\]])", r"\1", text)

    text = re.sub(r"([(\[\{])\s+", r"\1", text)

    text = re.sub(r"([،؛])(?=[آ-یA-Za-z])", r"\1 ", text)

    return text


def fix_pdf_hyphenation(text: str) -> str:
    """
    Join Latin words broken across PDF lines with a trailing hyphen.
    Restricted to an ASCII hyphen followed by a Latin-starting
    continuation line, so we don't accidentally eat a Persian
    en-dash or a numbered-list dash.
    """

    lines = text.splitlines()
    result = []

    for line in lines:
        line = line.strip()

        if not line:
            result.append("")
            continue

        if (
            result
            and result[-1].endswith("-")
            and re.match(r"^[A-Za-z]", line)
        ):
            result[-1] = result[-1][:-1] + line
        else:
            result.append(line)

    return "\n".join(result)


# ---------------------------------------------------------------------
# Header / footer cleanup (printout artifacts, e.g. from rc.majlis.ir)
# ---------------------------------------------------------------------

_BOILERPLATE_PATTERNS = [
    r"^https?://\S+$",                     # bare source URL line
    r"^\d+ of \d+$",                       # "8 of 1" page counters
    r"^(AM|PM) \d{1,2}:\d{2} \d{1,2}/\d{1,2}/\d{4},?$",  # print timestamp
    r"^طرح\s*ها\s*و\s*لوایح.*$",           # repeated majlis.ir page header
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE_PATTERNS))


def strip_boilerplate(text: str) -> str:
    lines = [ln for ln in text.splitlines() if not _BOILERPLATE_RE.match(ln.strip())]
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Native (text-layer) extraction - same approach as the original script
# ---------------------------------------------------------------------

def extract_page_native(page) -> str:
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
            {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "text": text.strip(), "word_no": word_no}
        )

    ordered_lines = sorted(
        lines.values(),
        key=lambda line: (
            min(w["y0"] for w in line),
            min(w["x0"] for w in line),
        ),
    )

    result = []

    for line in ordered_lines:
        line.sort(key=lambda w: w["x0"], reverse=True)
        text = " ".join(w["text"] for w in line)
        result.append(text)

    return "\n".join(result)


# ---------------------------------------------------------------------
# OCR fallback extraction (used when native text layer is broken)
# ---------------------------------------------------------------------

def extract_page_ocr(page) -> str:
    if not OCR_AVAILABLE:
        raise RuntimeError(
            "pytesseract/Pillow not installed - "
            "run: pip install pytesseract pillow, and install the "
            "Tesseract binary with the 'fas' language pack."
        )

    zoom = OCR_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    # psm 6: assume a single uniform block of text - works well for
    # dense, justified government-document pages like this one.
    config = "--psm 6"

    text = pytesseract.image_to_string(img, lang=OCR_LANG, config=config)

    return text.strip()


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def extract_with_pymupdf(path: Path) -> str:
    pages = []
    ocr_used_on = []

    with fitz.open(path) as document:
        for page_index, page in enumerate(document, start=1):

            native_text = extract_page_native(page)

            if is_corrupted(native_text):
                if OCR_AVAILABLE:
                    print(
                        f"  Page {page_index}: native text layer looks "
                        f"corrupted (score={corruption_score(native_text):.3f}) "
                        f"- falling back to OCR."
                    )
                    try:
                        page_text = extract_page_ocr(page)
                        ocr_used_on.append(page_index)
                    except Exception as exc:
                        print(f"    OCR failed ({exc}), keeping native text.")
                        page_text = native_text
                else:
                    print(
                        f"  Page {page_index}: native text layer looks "
                        f"corrupted (score={corruption_score(native_text):.3f}) "
                        f"but OCR is not available - install pytesseract "
                        f"+ Tesseract 'fas' data for better results."
                    )
                    page_text = native_text
            else:
                page_text = native_text

            if page_text:
                pages.append(page_text)

    if ocr_used_on:
        print(f"OCR fallback was used on pages: {ocr_used_on}")

    return "\n\n".join(pages)


def save_result(filename: str, text: str) -> None:
    output_file = OUTPUT_DIR / filename
    output_file.write_text(text, encoding="utf-8")
    print(f"Saved: {output_file}")


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"PDF file not found: {PDF_FILE}")

    print("Extracting with PyMuPDF (+ OCR fallback where needed)...")
    extracted_text = extract_with_pymupdf(PDF_FILE)

    print("Stripping headers/footers...")
    extracted_text = strip_boilerplate(extracted_text)

    print("Fixing hyphenation...")
    extracted_text = fix_pdf_hyphenation(extracted_text)

    print("Normalizing text...")
    extracted_text = normalize_text(extracted_text)
    extracted_text = fix_spacing(extracted_text)

    save_result("pymupdf_v5_ocr_fallback.txt", extracted_text)

    print("\nExtraction completed.")


if __name__ == "__main__":
    main()