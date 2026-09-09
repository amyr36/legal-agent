# importing liberaries
from db.base import Base

from sqlalchemy.orm import (
    mapped_column,
)

from sqlalchemy import (
    ForeignKey,
    Table,
)

# association table
docs_to_keywords = Table(
    "docs_to_keywords",
    Base.metadata,
    mapped_column("doc_id", ForeignKey("docs.doc_id")),
    mapped_column("keywords_id", ForeignKey("keywords.keywords_id")),
)