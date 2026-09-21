from pathlib import Path

from backend.tests.document_extractor import FileExtractor
from backend.tests.document_normalizer_service import TextNormalizer


TEST_FILE = Path("backend/tests/documents/hormuz.pdf")
OUTPUT_FILE = Path("backend/tests/output1/extraction_result.txt")


def test_pipeline() -> None:

    # --------------------------------------------------------
    # 1. Extract
    # --------------------------------------------------------

    extracted_text = FileExtractor.extract(
        TEST_FILE
    )

    # --------------------------------------------------------
    # 2. Normalize
    # --------------------------------------------------------

    normalized_text = TextNormalizer.normalize(
        extracted_text
    )

    # --------------------------------------------------------
    # 3. Create output directory
    # --------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 4. Save result
    # --------------------------------------------------------

    output = f"""
FILE
====
{TEST_FILE}

EXTRACTED TEXT
==============
{extracted_text}


NORMALIZED TEXT
===============
{normalized_text}


STATISTICS
==========
Extracted characters: {len(extracted_text)}
Normalized characters: {len(normalized_text)}
"""

    OUTPUT_FILE.write_text(
        output,
        encoding="utf-8",
    )

    print(
        f"Test completed: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    test_pipeline()