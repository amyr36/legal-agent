from pathlib import Path
import re
import time

import chromadb
from sentence_transformers import SentenceTransformer


# ============================================================
# Configuration
# ============================================================

TEXT_FILE = Path("tests/output/pymupdf_v4_2.txt")

MODEL_NAME = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

CHROMA_PATH = Path("tests/rag/output/chroma")
COLLECTION_NAME = "hormoz_legal_test"

TOP_K = 5


# ============================================================
# Normalization
# ============================================================

def normalize_digits(text: str) -> str:
    """
    Convert Persian and Arabic-Indic digits to English digits.

    Example:
        ماده ۱۲
        ->
        ماده 12
    """

    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )

    return text.translate(translation)


def normalize_id(text: str) -> str:
    """
    Normalize an article/document ID before comparison.
    """

    return normalize_digits(text.strip())


# ============================================================
# Embedding Service
# ============================================================

class EmbeddingService:

    def __init__(self, model_name: str):
        print(f"Loading embedding model: {model_name}")

        self.model = SentenceTransformer(model_name)

    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        return embeddings.tolist()

    def embed_query(
        self,
        text: str,
    ) -> list[float]:

        embedding = self.model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        return embedding.tolist()


# ============================================================
# Legal Chunker
# ============================================================

class LegalChunker:

    ARTICLE_PATTERN = re.compile(
        r"(?m)^ماده\s+([۰-۹0-9]+)\s*[_\-]?"
    )

    def split_articles(
        self,
        text: str,
    ) -> list[dict]:

        matches = list(
            self.ARTICLE_PATTERN.finditer(text)
        )

        articles = []

        for index, match in enumerate(matches):

            article_number = match.group(1)

            start = match.start()

            if index + 1 < len(matches):
                end = matches[index + 1].start()
            else:
                end = len(text)

            article_text = text[start:end].strip()

            article_number_normalized = normalize_digits(
                article_number
            )

            article_id = (
                f"hormoz_article_{article_number_normalized}"
            )

            articles.append(
                {
                    "id": article_id,
                    "article_number": article_number_normalized,
                    "text": article_text,
                }
            )

        return articles


# ============================================================
# ChromaDB Vector Store
# ============================================================

class VectorStore:

    def __init__(
        self,
        persist_path: Path,
        collection_name: str,
    ):

        persist_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.client = chromadb.PersistentClient(
            path=str(persist_path)
        )

        # Delete old test collection so every test starts clean.
        try:
            self.client.delete_collection(
                name=collection_name
            )
        except Exception:
            pass

        self.collection = self.client.create_collection(
            name=collection_name,
            metadata={
                "description": "Hormoz legal retrieval test"
            },
        )

    def add_articles(
        self,
        articles: list[dict],
        embeddings: list[list[float]],
    ):

        self.collection.add(
            ids=[
                article["id"]
                for article in articles
            ],
            documents=[
                article["text"]
                for article in articles
            ],
            embeddings=embeddings,
            metadatas=[
                {
                    "article_number": article[
                        "article_number"
                    ],
                    "document": "hormoz_law",
                }
                for article in articles
            ],
        )

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[str]:

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        return results["ids"][0]


# ============================================================
# Evaluation Dataset
# ============================================================

EVALUATION_DATASET = [

    {
        "question": "نظام حقوقی حاکم بر تنگه هرمز در کدام ماده تعیین شده است؟",
        "expected": {"hormoz_article_1"},
    },

    {
        "question": "اهداف قانون درباره امنیت تجارت و عبور ایمن از تنگه هرمز چیست؟",
        "expected": {"hormoz_article_2"},
    },

    {
        "question": "چه اقداماتی برای تامین امنیت پایدار در خلیج فارس مجاز دانسته شده است؟",
        "expected": {"hormoz_article_3"},
    },

    {
        "question": "چه نهادی مسئول صدور مجوز تردد ایمن از تنگه هرمز است؟",
        "expected": {"hormoz_article_4"},
    },

    {
        "question": "اجازه عبور کشتی‌ها به چه شرایطی وابسته است؟",
        "expected": {"hormoz_article_5"},
    },

    {
        "question": "آیا وسایل نقلیه دریایی وابسته به رژیم صهیونیستی اجازه عبور دارند؟",
        "expected": {"hormoz_article_6"},
    },

    {
        "question": "میزان عوارض عبور از تنگه هرمز چگونه تعیین می‌شود؟",
        "expected": {"hormoz_article_7"},
    },

    {
        "question": "آیا تحریم‌های یکجانبه می‌تواند دلیل امتناع از پرداخت عوارض باشد؟",
        "expected": {"hormoz_article_8"},
    },

    {
        "question": "چه کشورهایی می‌توانند از تخفیف عوارض عبور برخوردار شوند؟",
        "expected": {"hormoz_article_9"},
    },

    {
        "question": "عوارض کشورهای متخاصم چند برابر کشورهای دیگر تعیین شده است؟",
        "expected": {"hormoz_article_10"},
    },

    {
        "question": "کشورهای حاشیه خلیج فارس تحت چه شرایطی از پرداخت عوارض معاف می‌شوند؟",
        "expected": {"hormoz_article_11"},
    },

    {
        "question": "خسارت‌های وارد شده به کشور چگونه باید مطالبه شود؟",
        "expected": {"hormoz_article_12"},
    },

    {
        "question": "در صورت امتناع طرف متخاصم از پرداخت غرامت چه اقدامی امکان‌پذیر است؟",
        "expected": {"hormoz_article_13"},
    },
]


# ============================================================
# Metrics
# ============================================================

def hit_at_k(
    expected: set[str],
    retrieved: list[str],
    k: int,
) -> int:

    expected_normalized = {
        normalize_id(item)
        for item in expected
    }

    retrieved_normalized = [
        normalize_id(item)
        for item in retrieved[:k]
    ]

    return int(
        any(
            item in expected_normalized
            for item in retrieved_normalized
        )
    )


def reciprocal_rank(
    expected: set[str],
    retrieved: list[str],
) -> float:

    expected_normalized = {
        normalize_id(item)
        for item in expected
    }

    retrieved_normalized = [
        normalize_id(item)
        for item in retrieved
    ]

    for rank, item in enumerate(
        retrieved_normalized,
        start=1,
    ):

        if item in expected_normalized:
            return 1.0 / rank

    return 0.0


# ============================================================
# Main Test
# ============================================================

def test_hormoz_legal_retrieval():

    # --------------------------------------------------------
    # 1. Read document
    # --------------------------------------------------------

    if not TEXT_FILE.exists():
        raise FileNotFoundError(
            f"Text file not found: {TEXT_FILE}"
        )

    text = TEXT_FILE.read_text(
        encoding="utf-8"
    )

    print("=" * 70)
    print("HORMOZ LEGAL RETRIEVAL TEST")
    print("=" * 70)

    print(
        f"\nInput file: {TEXT_FILE}"
    )

    print(
        f"Characters: {len(text):,}"
    )

    # --------------------------------------------------------
    # 2. Split into articles
    # --------------------------------------------------------

    chunker = LegalChunker()

    articles = chunker.split_articles(text)

    print(
        f"Articles found: {len(articles)}"
    )

    if not articles:
        raise RuntimeError(
            "No articles were detected."
        )

    print("\nDetected articles:")

    for article in articles:
        print(
            f"  {article['id']} "
            f"-> {len(article['text'])} chars"
        )

    # --------------------------------------------------------
    # 3. Load embedding model
    # --------------------------------------------------------

    embedding_service = EmbeddingService(
        MODEL_NAME
    )

    # --------------------------------------------------------
    # 4. Create embeddings
    # --------------------------------------------------------

    print("\nCreating embeddings...")

    embedding_start = time.perf_counter()

    embeddings = embedding_service.embed_documents(
        [
            article["text"]
            for article in articles
        ]
    )

    embedding_time = (
        time.perf_counter()
        - embedding_start
    )

    print(
        f"Embedding time: "
        f"{embedding_time:.4f}s"
    )

    # --------------------------------------------------------
    # 5. Store in ChromaDB
    # --------------------------------------------------------

    vector_store = VectorStore(
        persist_path=CHROMA_PATH,
        collection_name=COLLECTION_NAME,
    )

    vector_store.add_articles(
        articles=articles,
        embeddings=embeddings,
    )

    print(
        f"Stored {len(articles)} articles "
        f"in ChromaDB."
    )

    # --------------------------------------------------------
    # 6. Evaluation
    # --------------------------------------------------------

    hit1_results = []
    hit3_results = []
    hit5_results = []

    reciprocal_ranks = []
    latencies = []

    print("\n")

    for item in EVALUATION_DATASET:

        question = item["question"]
        expected = item["expected"]

        print("-" * 70)

        print("Question:")
        print(question)

        print("\nExpected:")
        print(expected)

        # ----------------------------------------------------
        # Query embedding + retrieval
        # ----------------------------------------------------

        start_time = time.perf_counter()

        query_embedding = (
            embedding_service.embed_query(
                question
            )
        )

        retrieved = vector_store.search(
            query_embedding=query_embedding,
            top_k=TOP_K,
        )

        latency = (
            time.perf_counter()
            - start_time
        )

        # ----------------------------------------------------
        # Metrics
        # ----------------------------------------------------

        hit1 = hit_at_k(
            expected,
            retrieved,
            1,
        )

        hit3 = hit_at_k(
            expected,
            retrieved,
            3,
        )

        hit5 = hit_at_k(
            expected,
            retrieved,
            5,
        )

        rr = reciprocal_rank(
            expected,
            retrieved,
        )

        hit1_results.append(hit1)
        hit3_results.append(hit3)
        hit5_results.append(hit5)

        reciprocal_ranks.append(rr)
        latencies.append(latency)

        # ----------------------------------------------------
        # Output
        # ----------------------------------------------------

        print("\nRetrieved:")
        print(retrieved)

        print(
            f"\nHit@1: {hit1}"
        )

        print(
            f"Hit@3: {hit3}"
        )

        print(
            f"Hit@5: {hit5}"
        )

        print(
            f"Reciprocal Rank: {rr:.4f}"
        )

        print(
            f"Latency: {latency:.4f}s"
        )

    # ========================================================
    # Final Evaluation
    # ========================================================

    total = len(EVALUATION_DATASET)

    hit1 = sum(hit1_results) / total
    hit3 = sum(hit3_results) / total
    hit5 = sum(hit5_results) / total

    mrr = sum(reciprocal_ranks) / total

    average_latency = (
        sum(latencies) / total
    )

    print("\n")
    print("=" * 70)
    print("FINAL RETRIEVAL EVALUATION")
    print("=" * 70)

    print(
        f"Number of questions: {total}"
    )

    print(
        f"Hit@1:               {hit1 * 100:.2f}%"
    )

    print(
        f"Hit@3:               {hit3 * 100:.2f}%"
    )

    print(
        f"Hit@5:               {hit5 * 100:.2f}%"
    )

    print(
        f"MRR:                 {mrr:.4f}"
    )

    print(
        f"Average latency:     {average_latency:.4f}s"
    )

    print(
        f"Embedding time:      {embedding_time:.4f}s"
    )

    print("=" * 70)


# ============================================================
# Pytest Entry Point
# ============================================================

def test_retrieval():
    test_hormoz_legal_retrieval()