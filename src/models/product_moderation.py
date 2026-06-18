import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.database.base import Base


class ProductModeration(AsyncAttrs, Base):
    __tablename__ = "product_moderation"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    seller_id = Column(Uuid(as_uuid=True), nullable=False)
    category_id = Column(Uuid(as_uuid=True), nullable=False)
    kind = Column(String(50), nullable=False, default="CREATE")
    status = Column(String(50), nullable=False, default="PENDING")
    queue_priority = Column(Integer, nullable=False, default=0)
    json_before = Column(JSON, nullable=True)
    json_after = Column(JSON, nullable=True)
    source_event_at = Column(DateTime(timezone=True), nullable=True)

    assigned_moderator_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    decision_at = Column(DateTime(timezone=True), nullable=True)
    date_moderation = Column(DateTime(timezone=True), nullable=True)
    moderator_comment = Column(Text, nullable=True)
    blocking_reason_id = Column(
        Uuid(as_uuid=True),
        ForeignKey(
            "blocking_reasons.id",
            name="fk_product_moderation_blocking_reason_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    field_reports = relationship(
        "ModerationFieldReport",
        back_populates="product_moderation",
        cascade="all, delete-orphan",
    )
    blocking_reason = relationship("BlockingReason", back_populates="moderation_tickets")

    __table_args__ = (
        Index("idx_product_moderation_product_id", "product_id"),
        Index("idx_product_moderation_status", "status"),
        Index("idx_product_moderation_assigned_moderator_id", "assigned_moderator_id"),
    )
