from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud.document import document_crud
from app.models.document.document import Doc
from app.models.identity.user import User
from app.schemas.document_schema import DocumentUpdate
from app.services.document_extraction import extract_text


async def create_document(
    db: Session,
    title: str,
    organization_id: int,
    file,
    current_user: User,
    ) -> Doc:

    document = await document_crud.create_document(
        db=db,
        title=title,
        organization_id=organization_id,
        file=file,
        user_id=current_user.user_id,
    )

    try:
        extracted_path = _save_extracted_text(document.file_path)
    except Exception:
        # Rejecting the whole upload: no document without extracted
        # text is ever kept in the database or in storage.
        document_crud.delete_document(db, document)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract text from the uploaded PDF",
        )

    document_crud.set_extracted_path(
        db,
        document,
        extracted_path,
    )

    return document


def _save_extracted_text(file_path: str) -> str:
    """Extract the PDF text next to the original file and return the
    path of the saved .txt file."""
    extracted = extract_text(file_path, use_ocr=False)

    if not extracted.strip():
        raise ValueError("no text could be extracted from the PDF")

    extracted_path = (
        Path(file_path)
        .with_name("extracted.txt")
    )

    extracted_path.write_text(
        extracted,
        encoding="utf-8",
    )

    return str(extracted_path)


def get_document(
    db: Session,
    document_id: int,
    current_user: User,
) -> Doc | None:

    document = document_crud.get_document(
        db,
        document_id,
    )

    if document is None:
        return None

    if document.user_id != current_user.user_id:
        return None

    return document


def get_documents(
    db: Session,
    current_user: User,
) -> list[Doc]:

    return document_crud.get_documents_by_user(
        db,
        current_user.user_id,
    )


def update_document(
    db: Session,
    document_id: int,
    data: DocumentUpdate,
    current_user: User,
) -> Doc | None:

    document = document_crud.get_document(
        db,
        document_id,
    )

    if document is None:
        return None

    if document.user_id != current_user.user_id:
        return None

    update_data = data.model_dump(
        exclude_unset=True,
    )

    for field, value in update_data.items():
        setattr(document, field, value)

    return document_crud.update_document(
        db,
        document,
    )


def delete_document(
    db: Session,
    document_id: int,
    current_user: User,
) -> bool:

    document = document_crud.get_document(
        db,
        document_id,
    )

    if document is None:
        return False

    if document.user_id != current_user.user_id:
        return False

    document_crud.delete_document(
        db,
        document,
    )

    return True