# importing liberaries
from datetime import datetime

from app.db.base import Base

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    func
)


# building model
class Doc(Base):
    __tablename__ = "docs"

    doc_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String, nullable=False)

    file_path: Mapped[str] = mapped_column(String, nullable=False)

    extracted_path: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
    )

    structured_path: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
    )

    # pending | processing | done | partial | failed  (LLM structuring job)
    structure_status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="pending",
        server_default="pending",
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.organization_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user = relationship(
        "User",
        back_populates="documents"
    )

    organization = relationship(
        "Organization",
        back_populates="documents"
    )


    analyses = relationship(
        "Analysis",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    domains = relationship(
        "Domain",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    # self-referential relationship
    outgoing_relationships = relationship(
        "DocRelationship",
        foreign_keys="DocRelationship.source_doc_id",
        back_populates="source_document",
        cascade="all, delete-orphan",
    )

    incoming_relationships = relationship(
        "DocRelationship",
        foreign_keys="DocRelationship.target_doc_id",
        back_populates="target_document",
        cascade="all, delete-orphan",
    )
