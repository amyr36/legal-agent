# importing liberaries
from backend.app.db.base import Base
from backend.app.models.document.association_table import docs_to_keywords

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    Integer,
    String,
)


class Keyword(Base):
    __tablename__ = "keywords"

    keywords_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )
    keyword_text: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    documents = relationship(
        "Doc",
        secondary=docs_to_keywords,
        back_populates="keywords"
    )