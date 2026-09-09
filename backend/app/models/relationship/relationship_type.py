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
class RelationshipType(Base):
    __tablename__ = "relationship_types"

    type_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    name: Mapped[str] = mapped_column(String)

    doc_relationships = relationship(
        "DocRelationship",
        back_populates="relationship_type"
    )

    node_relationships = relationship(
        "NodeRelationship",
        back_populates="relationship_type"
    )