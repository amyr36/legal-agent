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
class Domain(Base):
    __tablename__ = "domains"

    domain_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    type: Mapped[str] = mapped_column(String)

    document = relationship(
        "Doc",
        back_populates="domains"
    )