# importing liberaries
from app.db.base import Base

from sqlalchemy import (
    Column,
    ForeignKey,
    Table,
)

# association table
docs_to_keywords = Table(
    "docs_to_keywords",
    Base.metadata,
    Column(
        "doc_id",
        ForeignKey("docs.doc_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "keywords_id",
        ForeignKey("keywords.keywords_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
        nullable=False,
    ),
)