from pathlib import Path
import re
import time

import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIG
# ============================================================

DOCUMENT_A = Path(
    "tests/doc_rag/hormuz1.txt"
)

DOCUMENT_B = Path(
    "tests/doc_rag/hormuz2.txt"
)

MODEL_NAME = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

TOP_K = 5

SIMILARITY_THRESHOLD = 0.70

MIN_ARTICLE_LENGTH = 80

MIN_LENGTH_RATIO = 0.20


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_digits(text: str) -> str:
    return text.translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789",
        )
    )


def normalize_persian(text: str) -> str:

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
        "\u200c": " ",
        "\u200f": " ",
        "\u200e": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# ARTICLE EXTRACTION
# ============================================================

ARTICLE_PATTERN_1 = re.compile(
    r"ماده\s*_?\s*([۰-۹0-9]+)"
)

ARTICLE_PATTERN_2 = re.compile(
    r"([۰-۹0-9]+)\s*ماده"
)


def extract_articles(text: str):

    text = normalize_persian(text)

    matches = []

    for match in ARTICLE_PATTERN_1.finditer(text):
        matches.append(
            (
                match.start(),
                match.end(),
                normalize_digits(
                    match.group(1)
                ),
            )
        )

    for match in ARTICLE_PATTERN_2.finditer(text):
        matches.append(
            (
                match.start(),
                match.end(),
                normalize_digits(
                    match.group(1)
                ),
            )
        )

    matches.sort(key=lambda x: x[0])

    articles = []

    for idx, (
        start,
        end,
        article_number,
    ) in enumerate(matches):

        if idx + 1 < len(matches):
            next_start = matches[idx + 1][0]
        else:
            next_start = len(text)

        article_text = (
            text[start:next_start]
            .strip()
        )

        if len(article_text) < MIN_ARTICLE_LENGTH:
            continue

        articles.append(
            {
                "id": f"article_{article_number}",
                "article_number": article_number,
                "text": article_text,
            }
        )

    return articles


# ============================================================
# FALLBACK CHUNKING
# ============================================================

def create_chunks(
    text: str,
    chunk_size: int = 700,
    overlap: int = 100,
):

    chunks = []

    start = 0
    idx = 0

    while start < len(text):

        end = min(
            start + chunk_size,
            len(text),
        )

        chunk_text = text[start:end]

        chunks.append(
            {
                "id": f"chunk_{idx}",
                "article_number": None,
                "text": chunk_text,
            }
        )

        if end >= len(text):
            break

        start = end - overlap
        idx += 1

    return chunks


# ============================================================
# LOAD DOCUMENT
# ============================================================

def load_document(path: Path):

    if not path.exists():
        raise FileNotFoundError(path)

    text = path.read_text(
        encoding="utf-8"
    )

    articles = extract_articles(text)

    if articles:
        return articles

    print(
        f"Warning: no articles found "
        f"in {path.name}"
    )

    return create_chunks(text)


# ============================================================
# EMBEDDINGS
# ============================================================

class EmbeddingService:

    def __init__(self):

        print(
            f"Loading model: "
            f"{MODEL_NAME}"
        )

        self.model = SentenceTransformer(
            MODEL_NAME
        )

    def encode(
        self,
        texts: list[str],
    ):

        return np.asarray(
            self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=True,
            )
        )


# ============================================================
# RETRIEVAL
# ============================================================

def retrieve_candidates(
    source_doc,
    source_embedding,
    target_docs,
    target_embeddings,
):

    similarities = np.dot(
        target_embeddings,
        source_embedding,
    )

    ranked = np.argsort(
        similarities
    )[::-1]

    results = []

    source_length = len(
        source_doc["text"]
    )

    for idx in ranked:

        candidate = target_docs[idx]

        score = float(
            similarities[idx]
        )

        # self-match
        if (
            candidate["id"]
            == source_doc["id"]
        ):
            continue

        # threshold
        if (
            score
            < SIMILARITY_THRESHOLD
        ):
            continue

        candidate_length = len(
            candidate["text"]
        )

        ratio = (
            min(
                source_length,
                candidate_length,
            )
            /
            max(
                source_length,
                candidate_length,
            )
        )

        # huge size mismatch
        if ratio < MIN_LENGTH_RATIO:
            continue

        results.append(
            {
                "id": candidate["id"],
                "score": score,
                "text": candidate["text"],
            }
        )

        if len(results) >= TOP_K:
            break

    return results


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("LEGAL SIMILARITY")
    print("=" * 80)

    print("\nLoading documents...")

    document_a = load_document(
        DOCUMENT_A
    )

    document_b = load_document(
        DOCUMENT_B
    )

    print(
        f"Document A: "
        f"{len(document_a)}"
    )

    print(
        f"Document B: "
        f"{len(document_b)}"
    )

    service = EmbeddingService()

    print("\nCreating embeddings...")

    start = time.perf_counter()

    embeddings_a = service.encode(
        [
            x["text"]
            for x in document_a
        ]
    )

    embeddings_b = service.encode(
        [
            x["text"]
            for x in document_b
        ]
    )

    elapsed = (
        time.perf_counter()
        - start
    )

    print(
        f"Embedding time: "
        f"{elapsed:.2f}s"
    )

    print("\n")
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)

    total_matches = 0

    for idx, source_doc in enumerate(
        document_a
    ):

        candidates = (
            retrieve_candidates(
                source_doc,
                embeddings_a[idx],
                document_b,
                embeddings_b,
            )
        )

        print("\n" + "-" * 80)
        print(
            f"Source: "
            f"{source_doc['id']}"
        )

        if not candidates:

            print(
                "No similar articles found."
            )

            continue

        total_matches += 1

        for rank, candidate in enumerate(
            candidates,
            start=1,
        ):

            print(
                f"\nRank {rank}"
            )

            print(
                f"ID: "
                f"{candidate['id']}"
            )

            print(
                f"Similarity: "
                f"{candidate['score']:.4f}"
            )

            print(
                f"Similarity (%): "
                f"{candidate['score']*100:.2f}%"
            )

    print("\n")
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(
        f"Sources: {len(document_a)}"
    )

    print(
        f"Matched: {total_matches}"
    )

    print(
        f"Threshold: "
        f"{SIMILARITY_THRESHOLD}"
    )


if __name__ == "__main__":
    main()