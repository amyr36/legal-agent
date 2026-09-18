"""Vector store management only: FAISS build/load, records → Documents,
metadata preservation.

Runnable standalone:  python -m services.vector_store_service
"""

import json
import os
from typing import Dict, List

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from core.config import (
    DOCUMENT_SLOTS,
    EMBEDDING_MODEL,
    METADATA_FIELDS,
    RECORD_INDEX_KEY,
)


# ---------------------------------------------------------------------------
# Internal path helpers
# ---------------------------------------------------------------------------


def _faiss_path(doc_key: str) -> str:
    return os.path.join(DOCUMENT_SLOTS[doc_key]["temp_dir"], "faiss")


def _chunks_path(doc_key: str) -> str:
    return os.path.join(DOCUMENT_SLOTS[doc_key]["temp_dir"], "chunks.jsonl")


# ---------------------------------------------------------------------------
# Fingerprint helpers
# ---------------------------------------------------------------------------


def _context_fingerprint(records: List[Dict]) -> str:
    ids = ",".join(str(r.get("id")) for r in records)
    return f"n={len(records)};ids={ids}"


def _load_saved_fingerprint(doc_key: str) -> str:
    path = os.path.join(_faiss_path(doc_key), "fingerprint.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


# ---------------------------------------------------------------------------
# Context I/O
# ---------------------------------------------------------------------------


def ensure_directories() -> None:
    for slot in DOCUMENT_SLOTS.values():
        os.makedirs(os.path.join(slot["temp_dir"], "faiss"), exist_ok=True)


def load_context(doc_key: str) -> List[Dict]:
    path = DOCUMENT_SLOTS[doc_key]["context_path"]
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Context file not found: {path}. Populate it with legal records "
            f"before running the pipeline."
        )
    records: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path} line {line_no}: {exc}") from exc
    return records


def save_context(doc_key: str, records: List[Dict]) -> str:
    path = DOCUMENT_SLOTS[doc_key]["context_path"]
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# Records → Documents
# ---------------------------------------------------------------------------


def records_to_documents(records: List[Dict]) -> List[Document]:
    documents: List[Document] = []
    for index, record in enumerate(records):
        metadata = {field: record.get(field) for field in METADATA_FIELDS}
        metadata[RECORD_INDEX_KEY] = index
        documents.append(
            Document(page_content=str(record.get("text", "")), metadata=metadata)
        )
    return documents


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


# ---------------------------------------------------------------------------
# FAISS build / load
# ---------------------------------------------------------------------------


def save_chunks(documents: List[Document], doc_key: str) -> str:
    path = _chunks_path(doc_key)
    with open(path, "w", encoding="utf-8") as f:
        for doc in documents:
            payload = {"text": doc.page_content, "metadata": doc.metadata}
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def build_faiss_for_document(doc_key: str, embeddings: HuggingFaceEmbeddings = None) -> "FAISS":
    ensure_directories()
    if embeddings is None:
        embeddings = get_embeddings()

    records = load_context(doc_key)
    if not records:
        raise ValueError(
            f"Context file for document {doc_key} is empty: "
            f"{DOCUMENT_SLOTS[doc_key]['context_path']}"
        )
    documents = records_to_documents(records)

    from langchain_community.vectorstores import FAISS

    vector_store = FAISS.from_documents(documents, embeddings)

    faiss_dir = _faiss_path(doc_key)
    vector_store.save_local(faiss_dir)
    with open(os.path.join(faiss_dir, "fingerprint.txt"), "w", encoding="utf-8") as f:
        f.write(_context_fingerprint(records))
    save_chunks(documents, doc_key)
    return vector_store


def load_faiss_for_document(
    doc_key: str, embeddings: HuggingFaceEmbeddings = None, rebuild: bool = False
) -> "FAISS":
    faiss_dir = _faiss_path(doc_key)
    index_file = os.path.join(faiss_dir, "index.faiss")
    if not rebuild and os.path.exists(index_file):
        records = load_context(doc_key)
        if _load_saved_fingerprint(doc_key) == _context_fingerprint(records):
            if embeddings is None:
                embeddings = get_embeddings()
            from langchain_community.vectorstores import FAISS

            return FAISS.load_local(
                faiss_dir, embeddings, allow_dangerous_deserialization=True
            )
        print(f"  [faiss] index for document {doc_key} is stale (context changed); rebuilding")
    return build_faiss_for_document(doc_key, embeddings)


def build_or_load_all(embeddings: HuggingFaceEmbeddings = None, rebuild: bool = False) -> Dict[str, "FAISS"]:
    if embeddings is None:
        embeddings = get_embeddings()
    return {
        doc_key: load_faiss_for_document(doc_key, embeddings, rebuild=rebuild)
        for doc_key in DOCUMENT_SLOTS
    }


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    print("=== services.vector_store_service (standalone) ===")
    emb = get_embeddings()
    stores = build_or_load_all(emb, rebuild=False)
    for key, vs in stores.items():
        print(f"  FAISS {key}: {len(vs.index_to_docstore_id)} vectors")