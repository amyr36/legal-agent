# importing liberaries
from datetime import datetime

from db.base import Base

from sqlalchemy import (
    Integer,
    Float,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)


# building model
class DocRelationship(Base):
    __tablename__ = "doc_relationships"

    relationship_doc_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    source_doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    target_doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    type_id: Mapped[int] = mapped_column(
        ForeignKey("relationship_types.type_id")
    )

    confidence_score: Mapped[float] = mapped_column(
        Float
    )

    detected_by_model: Mapped[str] = mapped_column(
        String
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    source_document = relationship(
        "Doc",
        foreign_keys=[source_doc_id],
        back_populates="outgoing_relationships"
    )

    target_document = relationship(
        "Doc",
        foreign_keys=[target_doc_id],
        back_populates="incoming_relationships"
    )

    relationship_type = relationship(
        "RelationshipType",
        back_populates="doc_relationships"
    )