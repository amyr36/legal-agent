# importing liberaries
from datetime import datetime

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
    DateTime,

)


# building model
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String)
    phone_number: Mapped[str] = mapped_column(String)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.role_id")
    )
    signup_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    role = relationship("Role", back_populates="users")
    documents = relationship("Doc", back_populates="user")