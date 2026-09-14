# importing liberaries
from app.db.base import Base

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    Integer,
    String,
)


# building model
class Organization(Base):
    __tablename__ = "organizations"

    organization_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    documents = relationship(
        "Doc",
        back_populates="organization",
        cascade="all, delete-orphan",
    )