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
    DateTime,
    JSONB,
)


# building model
class Analysis(Base):
    __tablename__ = "analysis"

    analysis_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    analysis_result: Mapped[dict] = mapped_column(
        JSONB
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    document = relationship(
        "Doc",
        back_populates="analyses"
    )

    keywords = relationship(
        "AnalysisKeyword",
        back_populates="analysis"
    )