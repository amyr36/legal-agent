from pathlib import Path
import aiofiles
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document.document import Doc


STORAGE_DIR = Path("/app/storage")


async def create_document(
    db: Session,
    title: str,
    organization_id: int,
    file: UploadFile,
    user_id: int,
) -> Doc:

    document = Doc(
        user_id=user_id,
        title=title,
        organization_id=organization_id,
        file_path="",
    )
    db.add(document)
    db.flush()

    # 2. Storing file in storage
    extension = Path(file.filename).suffix.lower()
    file_dir = STORAGE_DIR / str(user_id) / str(document.doc_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / f"original{extension}"

    async with aiofiles.open(file_path, "wb") as out:
        await out.write(await file.read())

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


def delete_document(
    db: Session,
    document: Doc,
    ) -> None:
    # Deleting file from storage
    if document.file_path:
        Path(document.file_path).unlink(missing_ok=True)

    db.delete(document)
    db.commit()




     

