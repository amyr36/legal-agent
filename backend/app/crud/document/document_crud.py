from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document.document import Doc


def create_document(
    db: Session,
    document: Doc,
) -> Doc:
    db.add(document)
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


def delete_document(
    db: Session,
    document: Doc,
) -> None:
    db.delete(document)
    db.commit()




     

