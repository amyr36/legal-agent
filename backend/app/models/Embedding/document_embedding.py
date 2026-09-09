# importing liberaries
from datetime import datetime

from backend.app.db.base import Base

# the extension to store vectors in PostgreSQL
from pgvector.sqlalchemy import Vector

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
    func,
)


# building model
class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    embedding_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    vector: Mapped[list[float]] = mapped_column(
        Vector(),
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

    document = relationship(
        "Doc",
        back_populates="embeddings"
    )