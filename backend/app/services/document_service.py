import json
import logging
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.file_config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
)
from app.crud.document import document_crud
from app.models.document.document import Doc
from app.models.identity.user import User
from app.schemas.document_schema import DocumentUpdate
from app.services.document_extraction import extract_pdf

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MB
PDF_MAGIC = b"%PDF-"


class ExtractionFailed(Exception):
    """Raised when no usable text could be extracted from the PDF."""


# ---------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------

async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    """Validate the upload (PDF only, max size) and return its bytes."""
    extension = Path(file.filename or "").suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files are accepted",
        )

    if (
        file.content_type
        and file.content_type != "application/octet-stream"
        and file.content_type not in ALLOWED_MIME_TYPES
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files are accepted",
        )

    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds the 20 MB limit",
            )
        chunks.append(chunk)

    content = b"".join(chunks)

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )

    if PDF_MAGIC not in content[:1024]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Uploaded file is not a valid PDF",
        )

    return content, extension


# ---------------------------------------------------------------------
# Create (single commit, full cleanup on failure)
# ---------------------------------------------------------------------

def _store_and_extract(
    db: Session,
    title: str,
    organization_id: int,
    user_id: int,
    content: bytes,
    extension: str,
) -> Doc:
    """
    Blocking work (DB, disk, PDF parsing). Runs in a worker thread.
    """
    doc_id: int | None = None

    try:
        document = document_crud.add_document(
            db,
            title=title,
            organization_id=organization_id,
            user_id=user_id,
        )
        doc_id = document.doc_id

        folder = document_crud.document_dir(doc_id)
        folder.mkdir(parents=True, exist_ok=True)

        original = folder / f"original{extension}"
        original.write_bytes(content)

        try:
            extracted = extract_pdf(original)
            if not extracted.text.strip():
                raise ValueError("no text could be extracted from the PDF")
        except Exception as exc:
            raise ExtractionFailed from exc

        text_path = folder / document_crud.EXTRACTED_TEXT_NAME
        text_path.write_text(extracted.text, encoding="utf-8")

        meta_path = folder / document_crud.EXTRACTED_META_NAME
        meta_path.write_text(
            json.dumps(extracted.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

        document.file_path = document_crud.to_relative(original)
        document.extracted_path = document_crud.to_relative(text_path)

        db.commit()
        db.refresh(document)
        return document

    except BaseException as exc:
        db.rollback()

        if doc_id is not None:
            _cleanup_folder(document_crud.document_dir(doc_id))

        if isinstance(exc, ExtractionFailed):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract text from the uploaded PDF",
            ) from exc

        if isinstance(exc, IntegrityError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid organization",
            ) from exc

        raise


def _cleanup_folder(folder: Path) -> None:
    """Remove files we created for a failed upload. Never raises."""
    try:
        for child in folder.iterdir():
            child.unlink(missing_ok=True)
        folder.rmdir()
    except OSError:
        pass


async def create_document(
    db: Session,
    title: str,
    organization_id: int,
    file: UploadFile,
    current_user: User,
) -> Doc:

    title = title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Title must not be empty",
        )

    organization_found = await run_in_threadpool(
        document_crud.organization_exists,
        db,
        organization_id,
    )
    if not organization_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    content, extension = await _read_upload(file)

    return await run_in_threadpool(
        _store_and_extract,
        db,
        title,
        organization_id,
        current_user.user_id,
        content,
        extension,
    )


# ---------------------------------------------------------------------
# Read / update / delete
# ---------------------------------------------------------------------

def get_document(db: Session, document_id: int, current_user: User) -> Doc | None:
    return document_crud.get_document(db, document_id)


def get_documents(
    db: Session,
    current_user: User,
    organization_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Doc]:
    return document_crud.get_documents(
        db, organization_id=organization_id, skip=skip, limit=limit
    )


def update_document(
    db: Session,
    document_id: int,
    data: DocumentUpdate,
    current_user: User,
) -> Doc | None:

    document = document_crud.get_document(db, document_id)
    if document is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    new_org_id = update_data.get("organization_id")
    if (
        new_org_id is not None
        and new_org_id != document.organization_id
        and not document_crud.organization_exists(db, new_org_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    for field, value in update_data.items():
        setattr(document, field, value)

    return document_crud.update_document(db, document)


def delete_document(db: Session, document_id: int, current_user: User) -> bool:
    document = document_crud.get_document(db, document_id)
    if document is None:
        return False
    document_crud.delete_document(db, document)
    return True


# ---------------------------------------------------------------------
# Structure extraction (background job)
# ---------------------------------------------------------------------

def run_structure_extraction(document_id: int) -> None:
    """
    Structure the extracted text with the LLM and store the result as JSONL,
    then build the per-document FAISS index.

    Each stage has its own try/except so a failure in the LAST stage does not
    overwrite the status of an earlier, successful stage.
    """
    from app.db.database import SessionLocal
    from app.services.text_to_json import structure_text

    db = SessionLocal()
    document: Doc | None = None

    try:
        document = document_crud.get_document(db, document_id)
        if document is None or not document.extracted_path:
            logger.warning(
                "structure extraction skipped: document %s missing or has no extracted_path",
                document_id,
            )
            return

        # --- Stage 1: structuring -------------------------------------
        document_crud.mark_structure_status(db, document, "processing")
        db.commit()  # FIX: persist the status change immediately

        text = document_crud.resolve_storage_path(
            document.extracted_path
        ).read_text(encoding="utf-8")

        result = structure_text(text)

        if not result.records:
            raise RuntimeError(f"structuring gave no usable result: {result.meta}")

        if result.failed_chunks:
            logger.warning(
                "Document %s: %d chunk(s) failed, rule-based fallback used: %s",
                document_id, result.failed_chunks, result.data.get("failed"),
            )

        jsonl_path = (
            document_crud.structured_path_for(document_id).with_suffix(".jsonl")
        )
        result.write_jsonl(jsonl_path)

        # FIX: mark done BEFORE building the index, so an indexing failure
        # does not demote the document back to "failed".
        document_crud.mark_structure_status(
            db,
            document,
            "done",
            structured_path=document_crud.to_relative(jsonl_path),
        )
        db.commit()

        meta = result.meta
        logger.info(
            "Structured document %s: %d records",
            document_id,
            len(result.records),
        )
        if (
            meta.get("unverified_ids")
            or meta.get("missing_article_numbers")
            or meta.get("suspect_ids")
        ):
            logger.warning(
                "Structured document %s needs review: unverified=%s "
                "missing_articles=%s suspect=%s",
                document_id,
                meta.get("unverified_ids"),
                meta.get("missing_article_numbers"),
                meta.get("suspect_ids"),
            )

        # --- Stage 2: indexing (best-effort) --------------------------
        # FIX: separate try so an embedding/FAISS failure is logged but does
        # not poison the document status. The document is already searchable
        # via its structured_path; the index can be rebuilt later.
        try:
            from app.services import vector_store

            faiss_dir = document_crud.document_dir(document_id) / "faiss"
            n_vectors = vector_store.build_faiss_from_records(
                result.records, faiss_dir
            )
            logger.info(
                "Indexed document %s: %d vectors", document_id, n_vectors
            )
        except Exception:
            logger.exception(
                "FAISS indexing failed for document %s (structured text is still stored)",
                document_id,
            )

    except Exception:
        logger.exception("Structure extraction failed for document %s", document_id)
        try:
            db.rollback()  # FIX: clear any poisoned state before writing status
            if document is not None:
                document_crud.mark_structure_status(db, document, "failed")
                db.commit()
        except Exception:
            logger.exception("Could not mark document %s as failed", document_id)
    finally:
        db.close()


def read_structure(
    db: Session,
    document_id: int,
    current_user: User,
) -> list[dict] | None:
    """Return the structured records (parsed from the JSONL file), or None."""
    document = document_crud.get_document(db, document_id)
    if document is None or not document.structured_path:
        return None

    # FIX: missing file is a 404, not a 500.
    path = document_crud.resolve_storage_path(document.structured_path)
    if not path.exists():
        logger.warning(
            "structured_path for document %s points to missing file %s",
            document_id,
            path,
        )
        return None

    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # FIX: don't let one bad line crash the whole read.
                logger.error(
                    "Bad JSON in %s at line %d: %s", path, line_no, exc
                )
                continue
    return records


def load_pair_stores(db: Session, doc_a_id: int, doc_b_id: int, current_user: User):
    from app.services import vector_store  # اسم واقعی فایل

    if doc_a_id == doc_b_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose two different documents")

    stores = {}
    for doc_id in (doc_a_id, doc_b_id):
        document = document_crud.get_document(db, doc_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document {doc_id} not found")
        if document.structure_status != "done" or not document.structured_path:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Document {doc_id} is not structured yet")

        faiss_dir = document_crud.document_dir(doc_id) / "faiss"
        try:
            stores[doc_id] = vector_store.load_faiss_from_dir(faiss_dir)
        except Exception:
            logger.warning("FAISS load failed for document %s; rebuilding", doc_id, exc_info=True)
            records = read_structure(db, doc_id, current_user)
            if not records:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Document {doc_id} has no records")
            try:
                vector_store.build_faiss_from_records(records, faiss_dir)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"Document {doc_id}: {exc}"
                ) from exc
            stores[doc_id] = vector_store.load_faiss_from_dir(faiss_dir)
    return stores