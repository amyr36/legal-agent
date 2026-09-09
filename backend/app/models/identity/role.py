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
class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String)

    users = relationship("User", back_populates="role")