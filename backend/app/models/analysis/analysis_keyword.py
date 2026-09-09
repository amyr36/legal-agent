# importing liberaries
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
)


# building model
class AnalysisKeyword(Base):
    __tablename__ = "analysis_keywords"

    analysis_keywords_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.analysis_id")
    )

    content: Mapped[str] = mapped_column(String)

    analysis = relationship(
        "Analysis",
        back_populates="keywords"
    )