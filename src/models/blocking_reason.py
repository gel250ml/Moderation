import uuid

from sqlalchemy import Boolean, Column, DateTime, String, Text, Uuid
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.sql import func

from src.database.base import Base


class BlockingReason(AsyncAttrs, Base):
    __tablename__ = "blocking_reasons"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    hard_block = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
