from pathlib import Path
import aiofiles
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.file_config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
)
from app.models.document.document import Doc


STORAGE_DIR = Path(settings.STORAGE_DIR)


async def create_document(
    db: Session,
    title: str,
    organization_id: int,
    file: UploadFile,
    user_id: int,
) -> Doc:

    # 1. Validating the uploaded file (PDF only, max 20 MB)
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

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds the 20 MB limit",
        )

    document = Doc(
        user_id=user_id,
        title=title,
        organization_id=organization_id,
        file_path="",
    )
    db.add(document)
    db.flush()

    # 2. Storing file in storage
    file_dir = STORAGE_DIR / str(user_id) / str(document.doc_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / f"original{extension}"

    async with aiofiles.open(file_path, "wb") as out:
        await out.write(content)

    # 3. Updating file path
    document.file_path = str(file_path)

    db.commit()
    db.refresh(document)
    return document


def get_document(
    db: Session,
    document_id: int,
) -> Doc | None:
    statement = select(Doc).where(
        Doc.doc_id == document_id
    )

    return db.scalar(statement)


def get_documents_by_user(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
) -> list[Doc]:
    statement = (
        select(Doc)
        .where(Doc.user_id == user_id)
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


def set_extracted_path(
    db: Session,
    document: Doc,
    extracted_path: str,
) -> Doc:
    document.extracted_path = extracted_path
    db.commit()
    db.refresh(document)

    return document


def delete_document(
    db: Session,
    document: Doc,
    ) -> None:
    # Deleting file from storage
    if document.file_path:
        Path(document.file_path).unlink(missing_ok=True)

    # Deleting extracted text file from storage
    if document.extracted_path:
        Path(document.extracted_path).unlink(missing_ok=True)

    # Removing the document's own storage folder when it is now empty
    if document.file_path:
        try:
            Path(document.file_path).parent.rmdir()
        except OSError:
            pass

    db.delete(document)
    db.commit()




     

