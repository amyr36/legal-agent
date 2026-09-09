# importing liberaries
from db.base import Base

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
    name: Mapped[str] = mapped_column(String)

    documents = relationship(
        "Doc",
        back_populates="organization"
    )