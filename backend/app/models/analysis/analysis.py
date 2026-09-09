# importing liberaries
from datetime import datetime

from backend.app.db.base import Base

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB


# building model
class Analysis(Base):
    __tablename__ = "analysis"

    analysis_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    analysis_result: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document = relationship(
        "Doc",
        back_populates="analyses"
    )

    keywords = relationship(
        "AnalysisKeyword",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )