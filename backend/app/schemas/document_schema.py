from pydantic import ConfigDict, BaseModel
from datetime import datetime
from typing import Optional



class DocumentCreate(BaseModel):
    title: str
    file_path: str


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    organization_id: Optional[int] = None


class DocumentRead(BaseModel):
    doc_id: int
    user_id: int
    organization_id: int
    title: str
    file_path: str
    created_at: datetime


    # Allow Pydantic to read values from object attributes
    model_config = ConfigDict(from_attributes=True)