# importing liberaries
from datetime import datetime

from db.base import Base

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    DateTime,
)


# building model
class DocVersion(Base):
    __tablename__ = "doc_versions"

    version_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    version_number: Mapped[int] = mapped_column(Integer)

    type: Mapped[str] = mapped_column(String)

    change_description: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    document = relationship(
        "Doc",
        back_populates="versions"
    )