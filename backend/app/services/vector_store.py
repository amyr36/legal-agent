import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document

from app.core.config import (
    DOCUMENT_SLOTS,
    EMBEDDING_MODEL,
    METADATA_FIELDS,
    RECORD_INDEX_KEY,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FIX: imports kept lazy for the heavy pieces, but the types are declared here
# ---------------------------------------------------------------------------

def _get_faiss_class():
    # FIX: single import site so every caller gets the same class object
    from langchain_community.vectorstores import FAISS
    return FAISS


# ---------------------------------------------------------------------------
# Internal path helpers (legacy A/B slots)
# ---------------------------------------------------------------------------

def _faiss_path(doc_key: str) -> str:
    return os.path.join(DOCUMENT_SLOTS[doc_key]["temp_dir"], "faiss")


def _chunks_path(doc_key: str) -> str:
    return os.path.join(DOCUMENT_SLOTS[doc_key]["temp_dir"], "chunks.jsonl")


# ---------------------------------------------------------------------------
# Fingerprint helpers (legacy A/B slots)
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
# Context I/O (legacy A/B slots)
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
                raise ValueError(
                    f"Invalid JSON at {path} line {line_no}: {exc}"
                ) from exc
    return records


def save_context(doc_key: str, records: List[Dict]) -> str:
    path = DOCUMENT_SLOTS[doc_key]["context_path"]
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# Records -> Documents
# ---------------------------------------------------------------------------

def records_to_documents(
    records: List[Dict],
    *,
    preserve_original_index: bool = False,
) -> List[Document]:
    """
    Convert records to LangChain Documents.

    FIX: when `preserve_original_index=True`, RECORD_INDEX_KEY is the position
    of the record in the ORIGINAL `records` list, not in the filtered output.
    This matters because the per-document index filters out non-article
    records, and downstream code that looks back into the JSONL file expects
    the original index.
    """
    documents: List[Document] = []
    for index, record in enumerate(records):
        metadata = {field: record.get(field) for field in METADATA_FIELDS}
        metadata[RECORD_INDEX_KEY] = index if preserve_original_index else len(documents)
        documents.append(
            Document(page_content=str(record.get("text", "")), metadata=metadata)
        )
    return documents


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)  # the model is heavy, load it once per process
def get_embeddings():
    # FIX: import inside the cached function so `lru_cache` also memoizes
    # the import cost, not just the model construction.
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def warm_embeddings() -> None:
    """FIX: call this once at app startup so the first request is not slow."""
    get_embeddings()


# ---------------------------------------------------------------------------
# Per-document index (used by the upload pipeline)
# ---------------------------------------------------------------------------

def build_faiss_from_records(
    records: List[Dict],
    faiss_dir: Path,
    embeddings=None,
) -> int:
    """
    Embed the article records of one document and save the FAISS index
    into faiss_dir. Returns the number of vectors.
    """
    # FIX: keep (original_index, record) pairs so RECORD_INDEX_KEY is correct.
    indexed: List[Tuple[int, Dict]] = [
        (i, r)
        for i, r in enumerate(records)
        if str(r.get("text", "")).strip()
    ]
    if not indexed:
        raise ValueError("no article records to index")

    documents: List[Document] = []
    for original_index, record in indexed:
        metadata = {field: record.get(field) for field in METADATA_FIELDS}
        metadata[RECORD_INDEX_KEY] = original_index
        documents.append(
            Document(page_content=str(record.get("text", "")), metadata=metadata)
        )

    FAISS = _get_faiss_class()
    store = FAISS.from_documents(documents, embeddings or get_embeddings())

    faiss_dir = Path(faiss_dir)
    faiss_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(faiss_dir))

    # FIX: write a small manifest so the index is self-describing.
    manifest = {
        "n_vectors": len(documents),
        "record_indices": [i for i, _ in indexed],
    }
    (faiss_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    return len(documents)


def load_faiss_from_dir(faiss_dir: Path, embeddings=None):
    """Load the index saved by build_faiss_from_records."""
    FAISS = _get_faiss_class()

    faiss_dir = Path(faiss_dir)
    index_file = faiss_dir / "index.faiss"
    if not index_file.exists():
        raise FileNotFoundError(f"FAISS index not found in {faiss_dir}")

    return FAISS.load_local(
        str(faiss_dir),
        embeddings or get_embeddings(),
        allow_dangerous_deserialization=True,  # written by this service
    )


# ---------------------------------------------------------------------------
# FAISS build / load (legacy A/B slots)
# ---------------------------------------------------------------------------

def save_chunks(documents: List[Document], doc_key: str) -> str:
    path = _chunks_path(doc_key)
    with open(path, "w", encoding="utf-8") as f:
        for doc in documents:
            payload = {"text": doc.page_content, "metadata": doc.metadata}
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def build_faiss_for_document(doc_key: str, embeddings=None):
    ensure_directories()
    if embeddings is None:
        embeddings = get_embeddings()

    records = load_context(doc_key)
    if not records:
        raise ValueError(
            f"Context file for document {doc_key} is empty: "
            f"{DOCUMENT_SLOTS[doc_key]['context_path']}"
        )
    documents = records_to_documents(records, preserve_original_index=True)

    FAISS = _get_faiss_class()
    vector_store = FAISS.from_documents(documents, embeddings)

    faiss_dir = _faiss_path(doc_key)
    vector_store.save_local(faiss_dir)
    with open(os.path.join(faiss_dir, "fingerprint.txt"), "w", encoding="utf-8") as f:
        f.write(_context_fingerprint(records))
    save_chunks(documents, doc_key)
    return vector_store


def load_faiss_for_document(doc_key: str, embeddings=None, rebuild: bool = False):
    faiss_dir = _faiss_path(doc_key)
    index_file = os.path.join(faiss_dir, "index.faiss")
    if not rebuild and os.path.exists(index_file):
        records = load_context(doc_key)
        if _load_saved_fingerprint(doc_key) == _context_fingerprint(records):
            if embeddings is None:
                embeddings = get_embeddings()
            FAISS = _get_faiss_class()
            return FAISS.load_local(
                faiss_dir, embeddings, allow_dangerous_deserialization=True
            )
        logger.info(
            "[faiss] index for document %s is stale (context changed); rebuilding",
            doc_key,
        )
    return build_faiss_for_document(doc_key, embeddings)


def build_or_load_all(embeddings=None, rebuild: bool = False) -> Dict[str, object]:
    if embeddings is None:
        embeddings = get_embeddings()
    return {
        doc_key: load_faiss_for_document(doc_key, embeddings, rebuild=rebuild)
        for doc_key in DOCUMENT_SLOTS
    }
  
