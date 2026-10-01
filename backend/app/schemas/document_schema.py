from datetime import datetime
from typing import Annotated, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class DocumentUpdate(BaseModel):
    """Partial update (used by PATCH). Only the fields that are sent
    are changed, and a sent field may not be null."""

    title: Optional[Title] = None
    organization_id: Optional[int] = Field(default=None, gt=0)

    @field_validator("title", "organization_id", mode="after")
    @classmethod
    def reject_explicit_null(cls, value):
        # Runs only for fields the client actually sent
        if value is None:
            raise ValueError("must not be null")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class DocumentRead(BaseModel):
    # Server file paths are intentionally NOT exposed
    doc_id: int
    user_id: int  # the uploader
    organization_id: int
    title: str
    structure_status: str
    created_at: datetime

    # Allow Pydantic to read values from object attributes
    model_config = ConfigDict(from_attributes=True)