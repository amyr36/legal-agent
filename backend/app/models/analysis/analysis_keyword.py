# importing liberaries
from app.db.base import Base

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
)


# building model
class AnalysisKeyword(Base):
    __tablename__ = "analysis_keywords"

    analysis_keywords_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.analysis_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(String, nullable=False)

    analysis = relationship(
        "Analysis",
        back_populates="keywords"
    )