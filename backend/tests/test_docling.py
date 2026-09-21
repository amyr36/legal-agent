from pathlib import Path

from docling.document_converter import DocumentConverter


TEST_DIR = Path(__file__).parent
PDF_FILE = TEST_DIR / "documents" / "ai.pdf"
OUTPUT_FILE = TEST_DIR / "output" / "docling_result3.md"


def main():
    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    converter = DocumentConverter()

    result = converter.convert(PDF_FILE)

    document = result.document

    markdown = document.export_to_markdown()

    OUTPUT_FILE.write_text(
        markdown,
        encoding="utf-8",
    )

    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()