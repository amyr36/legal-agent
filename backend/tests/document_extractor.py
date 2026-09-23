from pathlib import Path

import PyPDF2
import pdfplumber
import fitz


TEST_DIR = Path(__file__).parent
PDF_FILE = TEST_DIR / "documents" / "hormuz.pdf"
OUTPUT_DIR = TEST_DIR / "output"

OUTPUT_DIR.mkdir(exist_ok=True)


def extract_with_pypdf2(path: Path) -> str:
    pages = []

    with open(path, "rb") as file:
        reader = PyPDF2.PdfReader(file)

        for page in reader.pages:
            text = page.extract_text()

            if text:
                pages.append(text)

    return "\n\n".join(pages)


def extract_with_pdfplumber(path: Path) -> str:
    pages = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()

            if text:
                pages.append(text)

    return "\n\n".join(pages)


def extract_with_pymupdf(path: Path) -> str:
    pages = []

    document = fitz.open(path)

    for page in document:
        text = page.get_text()

        if text:
            pages.append(text)

    document.close()

    return "\n\n".join(pages)


def save_result(filename: str, text: str) -> None:
    output_file = OUTPUT_DIR / filename

    output_file.write_text(
        text,
        encoding="utf-8",
    )

    print(f"Saved: {output_file}")


def main() -> None:
    if not PDF_FILE.exists():
        raise FileNotFoundError(
            f"PDF file not found: {PDF_FILE}"
        )

    print("Extracting with PyPDF2...")
    pypdf2_text = extract_with_pypdf2(PDF_FILE)
    save_result("pypdf2.txt", pypdf2_text)

    print("Extracting with pdfplumber...")
    pdfplumber_text = extract_with_pdfplumber(PDF_FILE)
    save_result("pdfplumber.txt", pdfplumber_text)

    print("Extracting with PyMuPDF...")
    pymupdf_text = extract_with_pymupdf(PDF_FILE)
    save_result("pymupdf.txt", pymupdf_text)

    print("\nExtraction completed.")


if __name__ == "__main__":
    main()