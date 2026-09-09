# importing liberaries
from datetime import datetime

from db.base import Base

# the extension to store vectors in PostgreSQL
from pgvector.sqlalchemy import Vector

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    DateTime
)


# building model
class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    embedding_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    vector: Mapped[list[float]] = mapped_column(
        Vector()
    )

    detected_by_model: Mapped[str] = mapped_column(
        String
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    document = relationship(
        "Doc",
        back_populates="embeddings"
    )