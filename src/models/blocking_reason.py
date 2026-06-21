import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.database.base import Base


class BlockingReason(AsyncAttrs, Base):
    __tablename__ = "blocking_reasons"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    hard_block = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    moderation_tickets = relationship(
        "ProductModeration",
        back_populates="blocking_reason",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_blocking_reasons_code", "code", unique=True),
    )
