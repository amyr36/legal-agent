# importing liberaries
from datetime import datetime

from app.db.base import Base

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)


# building model
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )
    phone_number: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.role_id"),
        nullable=False,
        index=True,
    )
    signup_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    role = relationship("Role", back_populates="users")
    documents = relationship(
        "Doc",
        back_populates="user",
        cascade="all, delete-orphan",
    )