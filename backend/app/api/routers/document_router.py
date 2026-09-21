from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.database import get_db
from app.models.identity.user import User
from app.services import document_service


router = APIRouter(
    prefix="/document",
    tags=["Documents"],
)


@router.post("/")
def create_document(
    title: str = Form(...),
    organization_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return document_service.create_document(
        db=db,
        title=title,
        organization_id=organization_id,
        file=file,
        current_user=current_user,
    )