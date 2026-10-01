from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document.document import Doc


STORAGE_DIR = Path(settings.STORAGE_DIR).resolve()

EXTRACTED_TEXT_NAME = "extracted.txt"
EXTRACTED_META_NAME = "extracted.json"
STRUCTURED_JSON_NAME = "structured.json"


# ---------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------

def document_dir(doc_id: int) -> Path:
    """Folder that holds every file of one document."""
    return STORAGE_DIR / "docs" / str(doc_id)


def to_relative(path: Path) -> str:
    """Path as stored in the database: relative to STORAGE_DIR."""
    return path.resolve().relative_to(STORAGE_DIR).as_posix()


def resolve_storage_path(stored_path: str) -> Path:
    """
    Turn a stored path into an absolute path, refusing anything that
    escapes STORAGE_DIR. Works for new relative paths and for old rows
    that stored an absolute path inside STORAGE_DIR.
    """
    path = (STORAGE_DIR / stored_path).resolve()
    if path != STORAGE_DIR and STORAGE_DIR not in path.parents:
        raise ValueError("Stored path points outside the storage directory")
    return path


def remove_document_files(
    file_path: str | None,
    extracted_path: str | None,
) -> None:
    """Best-effort removal of a document's files. Never raises."""
    if not file_path:
        return

    try:
        original = resolve_storage_path(file_path)
        folder = original.parent

        targets = [original, folder / EXTRACTED_META_NAME, folder / STRUCTURED_JSON_NAME]
        if extracted_path:
            targets.append(resolve_storage_path(extracted_path))

        for target in targets:
            target.unlink(missing_ok=True)

        # Remove the document's own folder when it is now empty
        if folder != STORAGE_DIR:
            folder.rmdir()
    except (OSError, ValueError):
        pass

def structured_path_for(
    doc_id: int
    )-> Path:
    return document_dir(doc_id) / STRUCTURED_JSON_NAME


# ---------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------


def mark_structure_status(
    db: Session,
    document: Doc,
    status: str,
    structured_path: str | None = None,
) -> Doc:
    """Update structure status (and path on success) in one place."""
    document.structure_status = status
    if structured_path is not None:
        document.structured_path = structured_path
    db.commit()
    db.refresh(document)
    return document

def add_document(
    db: Session,
    title: str,
    organization_id: int,
    user_id: int,
) -> Doc:
    """Insert the row and flush to get doc_id. Does NOT commit."""
    document = Doc(
        user_id=user_id,  # uploader
        title=title,
        organization_id=organization_id,
        file_path="",
    )
    db.add(document)
    db.flush()
    return document


def get_document(
    db: Session,
    document_id: int,
) -> Doc | None:
    return db.scalar(
        select(Doc).where(Doc.doc_id == document_id)
    )


def organization_exists(
    db: Session,
    organization_id: int,
) -> bool:
    # Resolve the Organization class through the Doc relationship so this
    # file does not need to know where the Organization model lives.
    organization_model = Doc.organization.property.mapper.class_
    return db.get(organization_model, organization_id) is not None


def get_documents(
    db: Session,
    organization_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Doc]:
    statement = select(Doc)

    if organization_id is not None:
        statement = statement.where(Doc.organization_id == organization_id)

    statement = (
        statement
        .order_by(Doc.created_at.desc(), Doc.doc_id.desc())
        .offset(skip)
        .limit(limit)
    )

    return list(db.scalars(statement).all())


def update_document(
    db: Session,
    document: Doc,
) -> Doc:
    db.commit()
    db.refresh(document)
    return document


def delete_document(
    db: Session,
    document: Doc,
) -> None:
    """Delete the row first; only then remove files (best effort)."""
    file_path = document.file_path
    extracted_path = document.extracted_path

    db.delete(document)
    db.commit()

    remove_document_files(file_path, extracted_path)