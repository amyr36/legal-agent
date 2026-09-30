from pathlib import Path
import re
import time

from sentence_transformers import SentenceTransformer
import numpy as np


# ============================================================
# Configuration
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

# Similarity threshold.
# This is NOT an evaluation metric.
# It is only used to optionally classify candidates.
SIMILARITY_THRESHOLD = 0.60


# ============================================================
# Text normalization
# ============================================================

def normalize_persian(text: str) -> str:
    """
    Basic Persian normalization.

    Important:
    We normalize Unicode variants, but we do NOT reverse
    word order or aggressively modify the text.
    """

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
        "\u200c": " ",
        "\u200f": " ",
        "\u200e": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Normalize multiple spaces
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# Article extraction
# ============================================================

ARTICLE_PATTERN_1 = re.compile(
    r"ماده\s*[_\-]?\s*([۰-۹0-9]+)"
)

ARTICLE_PATTERN_2 = re.compile(
    r"([۰-۹0-9]+)\s*ماده"
)


def normalize_digits(text: str) -> str:

    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )

    return text.translate(translation)


def extract_articles(text: str) -> list[dict]:
    """
    Extract legal articles from both reasonably ordered
    and OCR-reversed text.

    The second file has OCR artifacts such as:

        _ ۱ ماده

    while the first file contains:

        ماده ۱

    Therefore both patterns are supported.
    """

    text = normalize_persian(text)

    matches = []

    # --------------------------------------------------------
    # Pattern:
    # ماده 1
    # --------------------------------------------------------

    for match in ARTICLE_PATTERN_1.finditer(text):
        matches.append(
            (
                match.start(),
                match.end(),
                normalize_digits(match.group(1)),
            )
        )

    # --------------------------------------------------------
    # Pattern:
    # 1 ماده
    # --------------------------------------------------------

    for match in ARTICLE_PATTERN_2.finditer(text):
        matches.append(
            (
                match.start(),
                match.end(),
                normalize_digits(match.group(1)),
            )
        )

    # Sort by position
    matches.sort(key=lambda x: x[0])

    # Remove duplicate article numbers when the same article
    # was detected by both patterns.
    unique_matches = []

    seen_positions = set()

    for start, end, number in matches:

        key = (start, number)

        if key in seen_positions:
            continue

        seen_positions.add(key)

        unique_matches.append(
            (start, end, number)
        )

    articles = []

    for index, (start, end, number) in enumerate(
        unique_matches
    ):

        if index + 1 < len(unique_matches):
            next_start = unique_matches[index + 1][0]
        else:
            next_start = len(text)

        article_text = text[start:next_start].strip()

        # Avoid tiny false-positive matches
        if len(article_text) < 50:
            continue

        articles.append(
            {
                "id": f"article_{number}",
                "article_number": number,
                "text": article_text,
            }
        )

    return articles


# ============================================================
# Generic chunking fallback
# ============================================================

def create_fallback_chunks(
    text: str,
    chunk_size: int = 700,
    overlap: int = 100,
) -> list[dict]:

    text = normalize_persian(text)

    chunks = []

    start = 0
    index = 0

    while start < len(text):

        end = min(
            start + chunk_size,
            len(text),
        )

        chunk_text = text[start:end].strip()

        if chunk_text:
            chunks.append(
                {
                    "id": f"chunk_{index}",
                    "article_number": None,
                    "text": chunk_text,
                }
            )

        if end >= len(text):
            break

        start = end - overlap
        index += 1

    return chunks


# ============================================================
# Document loading
# ============================================================

def load_document(
    path: Path,
) -> list[dict]:

    if not path.exists():
        raise FileNotFoundError(
            f"Document not found: {path}"
        )

    text = path.read_text(
        encoding="utf-8"
    )

    articles = extract_articles(text)

    if articles:
        return articles

    print(
        f"Warning: no articles detected in {path.name}. "
        f"Using generic chunks."
    )

    return create_fallback_chunks(text)


# ============================================================
# Embedding
# ============================================================

class EmbeddingService:

    def __init__(self, model_name: str):

        print(
            f"Loading model: {model_name}"
        )

        self.model = SentenceTransformer(
            model_name
        )

    def encode(
        self,
        texts: list[str],
    ) -> np.ndarray:

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=True,
        )

        return np.asarray(embeddings)


# ============================================================
# Similarity
# ============================================================

def cosine_similarity(
    query_embedding: np.ndarray,
    document_embeddings: np.ndarray,
) -> np.ndarray:
    """
    Because embeddings are normalized,
    cosine similarity is simply the dot product.
    """

    return np.dot(
        document_embeddings,
        query_embedding,
    )


# ============================================================
# Retrieve similar candidates
# ============================================================

def retrieve_candidates(
    source_chunk: dict,
    source_embedding: np.ndarray,
    target_chunks: list[dict],
    target_embeddings: np.ndarray,
    top_k: int,
) -> list[dict]:

    similarities = cosine_similarity(
        source_embedding,
        target_embeddings,
    )

    ranked_indices = np.argsort(
        similarities
    )[::-1]

    candidates = []

    for rank, index in enumerate(
        ranked_indices[:top_k],
        start=1,
    ):

        candidate = target_chunks[index]

        candidates.append(
            {
                "rank": rank,
                "id": candidate["id"],
                "article_number": candidate[
                    "article_number"
                ],
                "similarity": float(
                    similarities[index]
                ),
                "text": candidate["text"],
            }
        )

    return candidates


# ============================================================
# Main similarity pipeline
# ============================================================

def run_similarity_pipeline():

    print("=" * 80)
    print("LEGAL DOCUMENT SIMILARITY")
    print("=" * 80)

    # --------------------------------------------------------
    # Load documents
    # --------------------------------------------------------

    print("\nLoading documents...")

    document_a = load_document(
        DOCUMENT_A
    )

    document_b = load_document(
        DOCUMENT_B
    )

    print(
        f"Document A chunks/articles: "
        f"{len(document_a)}"
    )

    print(
        f"Document B chunks/articles: "
        f"{len(document_b)}"
    )

    # --------------------------------------------------------
    # Load model
    # --------------------------------------------------------

    embedding_service = EmbeddingService(
        MODEL_NAME
    )

    # --------------------------------------------------------
    # Create embeddings
    # --------------------------------------------------------

    print("\nCreating embeddings...")

    start = time.perf_counter()

    embeddings_a = embedding_service.encode(
        [
            item["text"]
            for item in document_a
        ]
    )

    embeddings_b = embedding_service.encode(
        [
            item["text"]
            for item in document_b
        ]
    )

    embedding_time = (
        time.perf_counter() - start
    )

    print(
        f"Embedding time: "
        f"{embedding_time:.4f}s"
    )

    # --------------------------------------------------------
    # Cross-document retrieval
    # --------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("SIMILAR CANDIDATES")
    print("=" * 80)

    all_results = []

    for index, source_chunk in enumerate(
        document_a
    ):

        source_embedding = embeddings_a[index]

        candidates = retrieve_candidates(
            source_chunk=source_chunk,
            source_embedding=source_embedding,
            target_chunks=document_b,
            target_embeddings=embeddings_b,
            top_k=TOP_K,
        )

        print("\n" + "-" * 80)

        print(
            f"Source: "
            f"{source_chunk['id']}"
        )

        print("\nSource text:")
        print(
            source_chunk["text"][:700]
        )

        print("\nSimilar candidates:")

        for candidate in candidates:

            print(
                f"\nRank {candidate['rank']}"
            )

            print(
                f"ID: {candidate['id']}"
            )

            print(
                f"Similarity: "
                f"{candidate['similarity']:.4f}"
            )

            print(
                f"Similarity (%): "
                f"{candidate['similarity'] * 100:.2f}%"
            )

            print(
                f"Text: "
                f"{candidate['text'][:500]}"
            )

        all_results.append(
            {
                "source": source_chunk,
                "candidates": candidates,
            }
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    for result in all_results:

        source = result["source"]
        candidates = result["candidates"]

        best = candidates[0]

        print(
            f"\n{source['id']}"
        )

        print(
            f"Best candidate: "
            f"{best['id']}"
        )

        print(
            f"Similarity: "
            f"{best['similarity']:.4f}"
        )

        print(
            f"Similarity: "
            f"{best['similarity'] * 100:.2f}%"
        )

        if (
            best["similarity"]
            >= SIMILARITY_THRESHOLD
        ):
            print(
                "Status: SIMILAR"
            )
        else:
            print(
                "Status: LOW SIMILARITY"
            )

    print("\n")
    print("=" * 80)
    print("DONE")
    print("=" * 80)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    run_similarity_pipeline()