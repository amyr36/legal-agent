from datetime import datetime

from sqlalchemy import (
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base


class DocNode(Base):
    __tablename__ = "doc_nodes"

    node_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id")
    )

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("doc_nodes.node_id"),
        nullable=True
    )

    node_type: Mapped[str] = mapped_column(
        String
    )

    node_title: Mapped[str | None] = mapped_column(
        String,
        nullable=True
    )

    content: Mapped[str] = mapped_column(
        Text
    )

    level: Mapped[int] = mapped_column(
        Integer
    )

    order_index: Mapped[int] = mapped_column(
        Integer
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    document = relationship(
        "Doc",
        back_populates="nodes"
    )

    # self-referential
    parent = relationship(
        "DocNode",
        remote_side=[node_id],
        back_populates="children"
    )

    children = relationship(
        "DocNode",
        back_populates="parent"
    )

    # graph relationships
    outgoing_relationships = relationship(
        "NodeRelationship",
        foreign_keys="NodeRelationship.source_node_id",
        back_populates="source_node"
    )

    incoming_relationships = relationship(
        "NodeRelationship",
        foreign_keys="NodeRelationship.target_node_id",
        back_populates="target_node"
    )