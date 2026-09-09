# importing liberaries
from datetime import datetime

from db.base import Base

from association_table import docs_to_keywords

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
    Text,
)


# building model
class Doc(Base):
    __tablename__ = "docs"

    doc_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id")
    )

    title: Mapped[str] = mapped_column(String)

    file_path: Mapped[str] = mapped_column(String)

    content: Mapped[str] = mapped_column(Text)

    normal_text: Mapped[str] = mapped_column(Text)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.organization_id")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    user = relationship(
        "User",
        back_populates="documents"
    )

    organization = relationship(
        "Organization",
        back_populates="documents"
    )

    # many-to-many
    keywords = relationship(
        "Keyword",
        secondary=docs_to_keywords,
        back_populates="documents"
    )

    versions = relationship(
        "DocVersion",
        back_populates="document"
    )

    analyses = relationship(
        "Analysis",
        back_populates="document"
    )

    domains = relationship(
        "Domain",
        back_populates="document"
    )

    nodes = relationship(
        "DocNode",
        back_populates="document"
    )

    embeddings = relationship(
        "DocumentEmbedding",
        back_populates="document"
    )

    # self-referential relationship
    outgoing_relationships = relationship(
        "DocRelationship",
        foreign_keys="DocRelationship.source_doc_id",
        back_populates="source_document"
    )

    incoming_relationships = relationship(
        "DocRelationship",
        foreign_keys="DocRelationship.target_doc_id",
        back_populates="target_document"
    )