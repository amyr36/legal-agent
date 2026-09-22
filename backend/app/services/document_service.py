from sqlalchemy.orm import Session

from app.crud.document import document_crud
from app.models.document.document import Doc
from app.models.identity.user import User
from app.schemas.document_schema import DocumentUpdate


async def create_document(
    db: Session,
    title: str,
    organization_id: int,
    file,
    current_user: User,
    ) -> Doc:

    return await document_crud.create_document(
        db=db,
        title=title,
        organization_id=organization_id,
        file=file,
        user_id=current_user.user_id,
    )


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