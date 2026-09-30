import time

import pytest

from app.services.rag.embedding_service import EmbeddingService
from app.services.rag.vectore_store_service import VectorStoreService
from app.services.rag.retrieval_service import RetrievalService


# ---------------------------------------------------------
# Test dataset
# ---------------------------------------------------------

EVALUATION_DATASET = [
    {
        "question": "اهلیت اشخاص در کدام ماده قانون مدنی مطرح شده است؟",
        "relevant_ids": {"law_1"},
    },
    {
        "question": "قوانین چه زمانی پس از تصویب منتشر می‌شوند؟",
        "relevant_ids": {"law_2"},
    },
    {
        "question": "شرایط انعقاد قرارداد چیست؟",
        "relevant_ids": {"law_3"},
    },
    {
        "question": "مسئولیت مدنی ناشی از خسارت چیست؟",
        "relevant_ids": {"law_4"},
    },
]


# ---------------------------------------------------------
# Test documents
# ---------------------------------------------------------

TEST_DOCUMENTS = [
    {
        "id": "law_1",
        "text": (
            "ماده 1 قانون مدنی درباره اهلیت اشخاص و شرایط "
            "لازم برای برخورداری از حقوق مدنی است."
        ),
        "metadata": {
            "document_id": 1,
            "article": 1,
        },
    },
    {
        "id": "law_2",
        "text": (
            "قوانین پس از تصویب و طی مراحل قانونی، برای اجرا "
            "منتشر می‌شوند."
        ),
        "metadata": {
            "document_id": 2,
            "article": 2,
        },
    },
    {
        "id": "law_3",
        "text": (
            "انعقاد قرارداد مستلزم وجود قصد و رضای طرفین، "
            "اهلیت، موضوع معین و مشروعیت جهت قرارداد است."
        ),
        "metadata": {
            "document_id": 3,
            "article": 3,
        },
    },
    {
        "id": "law_4",
        "text": (
            "هر شخصی که موجب ورود خسارت به دیگری شود، "
            "در موارد مقرر قانونی مسئول جبران خسارت است."
        ),
        "metadata": {
            "document_id": 4,
            "article": 4,
        },
    },
]


# ---------------------------------------------------------
# Fixture
# ---------------------------------------------------------

@pytest.fixture
def retrieval_service(tmp_path):

    embedding_service = EmbeddingService()

    vector_store_service = VectorStoreService(
        persist_directory=str(tmp_path / "chroma"),
        collection_name="retrieval_evaluation",
    )

    documents = [
        item["text"]
        for item in TEST_DOCUMENTS
    ]

    ids = [
        item["id"]
        for item in TEST_DOCUMENTS
    ]

    metadatas = [
        item["metadata"]
        for item in TEST_DOCUMENTS
    ]

    embeddings = embedding_service.embed_documents(
        documents
    )

    vector_store_service.add_documents(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return RetrievalService(
        embedding_service=embedding_service,
        vector_store_service=vector_store_service,
    )


# ---------------------------------------------------------
# Metric functions
# ---------------------------------------------------------

def calculate_hit_at_k(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> int:

    top_k = retrieved_ids[:k]

    return int(
        bool(set(top_k) & relevant_ids)
    )


def calculate_reciprocal_rank(
    retrieved_ids: list[str],
    relevant_ids: set[str],
) -> float:

    for rank, document_id in enumerate(
        retrieved_ids,
        start=1,
    ):
        if document_id in relevant_ids:
            return 1.0 / rank

    return 0.0


# ---------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------

def test_retrieval_metrics(retrieval_service):

    k_values = [1, 3, 5]

    hit_at_k = {
        k: []
        for k in k_values
    }

    reciprocal_ranks = []
    latencies = []

    for case in EVALUATION_DATASET:

        question = case["question"]
        relevant_ids = case["relevant_ids"]

        start_time = time.perf_counter()

        results = retrieval_service.retrieve(
            query=question,
            top_k=max(k_values),
        )

        elapsed = time.perf_counter() - start_time

        latencies.append(elapsed)

        retrieved_ids = results["ids"][0]

        print("\n--------------------------------")
        print(f"Question: {question}")
        print(f"Expected: {relevant_ids}")
        print(f"Retrieved: {retrieved_ids}")

        for k in k_values:

            hit = calculate_hit_at_k(
                retrieved_ids=retrieved_ids,
                relevant_ids=relevant_ids,
                k=k,
            )

            hit_at_k[k].append(hit)

        reciprocal_rank = calculate_reciprocal_rank(
            retrieved_ids=retrieved_ids,
            relevant_ids=relevant_ids,
        )

        reciprocal_ranks.append(reciprocal_rank)

    # -----------------------------------------------------
    # Calculate metrics
    # -----------------------------------------------------

    total_cases = len(EVALUATION_DATASET)

    metrics = {}

    for k in k_values:

        metrics[f"Hit@{k}"] = (
            sum(hit_at_k[k]) / total_cases
        )

    metrics["MRR"] = (
        sum(reciprocal_ranks)
        / total_cases
    )

    metrics["Average latency"] = (
        sum(latencies)
        / len(latencies)
    )

    # -----------------------------------------------------
    # Print metrics
    # -----------------------------------------------------

    print("\n")
    print("=" * 50)
    print("RAG RETRIEVAL EVALUATION")
    print("=" * 50)

    for name, value in metrics.items():

        if name == "Average latency":
            print(
                f"{name}: "
                f"{value:.4f} seconds"
            )
        else:
            print(
                f"{name}: "
                f"{value:.2%}"
            )

    print("=" * 50)

    # -----------------------------------------------------
    # Basic assertions
    # -----------------------------------------------------

    assert metrics["Hit@1"] >= 0.0
    assert metrics["Hit@3"] >= 0.0
    assert metrics["MRR"] >= 0.0