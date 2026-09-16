from sqlalchemy.orm import Session

from app.crud.document import document_crud
from app.models.document.document import Doc
from app.models.identity.user import User
from app.schemas.document.document_schema import (
    CreateDocument,
    UpdateDocument,
)


def create_document(
    db: Session,
    normal_text: str,
    data: CreateDocument,
    current_user: User,
) -> Doc:
    """
    Create a document for the authenticated user.

    normal_text = analysis_service.normalize(data.content)
    """

    document = Doc(
        user_id=current_user.user_id,
        title=data.title,
        file_path=data.file_path,
        content=data.content,
        normal_text=normal_text,
        organization_id=data.organization_id,
    )

    return document_crud.create_document(db, document)


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
    data: UpdateDocument,
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

    if "content" in update_data:
        # TODO:
        # document.normal_text = analysis_service.normalize(
        #     update_data["content"]
        # )
        pass

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