from datetime import datetime

from backend.app.db.base import Base

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)


class DocNode(Base):
    __tablename__ = "doc_nodes"

    node_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    doc_id: Mapped[int] = mapped_column(
        ForeignKey("docs.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("doc_nodes.node_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    node_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    node_title: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    # graph relationships
    outgoing_relationships = relationship(
        "NodeRelationship",
        foreign_keys="NodeRelationship.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )

    incoming_relationships = relationship(
        "NodeRelationship",
        foreign_keys="NodeRelationship.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )