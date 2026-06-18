import uuid

from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint, Uuid
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.sql import func

from src.database.base import Base


class ProcessedEvent(AsyncAttrs, Base):
    __tablename__ = "processed_events"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_service = Column(String(50), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "sender_service",
            "idempotency_key",
            name="uq_processed_events_sender_idempotency_key",
        ),
        Index("idx_processed_events_sender_service", "sender_service"),
    )
