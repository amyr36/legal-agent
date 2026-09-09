from datetime import datetime

from sqlalchemy import (
    Integer,
    Float,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base


class NodeRelationship(Base):
    __tablename__ = "node_relationships"

    relationship_node_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("doc_nodes.node_id")
    )

    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("doc_nodes.node_id")
    )

    type_id: Mapped[int] = mapped_column(
        ForeignKey("relationship_types.type_id")
    )

    confidence_score: Mapped[float] = mapped_column(
        Float
    )

    detected_by_model: Mapped[str] = mapped_column(
        String
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    source_node = relationship(
        "DocNode",
        foreign_keys=[source_node_id],
        back_populates="outgoing_relationships"
    )

    target_node = relationship(
        "DocNode",
        foreign_keys=[target_node_id],
        back_populates="incoming_relationships"
    )

    relationship_type = relationship(
        "RelationshipType",
        back_populates="node_relationships"
    )