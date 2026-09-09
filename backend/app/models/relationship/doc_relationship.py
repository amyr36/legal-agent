# importing liberaries
from datetime import datetime

from backend.app.db.base import Base

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
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
        ForeignKey("docs.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    target_doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type_id: Mapped[int] = mapped_column(
        ForeignKey("relationship_types.type_id"),
        nullable=False,
        index=True,
    )

    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    detected_by_model: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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