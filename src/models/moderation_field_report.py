import uuid

from sqlalchemy import Column, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import relationship

from src.database.base import Base


class ModerationFieldReport(AsyncAttrs, Base):
    __tablename__ = "field_reports"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_moderation_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("product_moderation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name = Column(String(100), nullable=False)
    sku_id = Column(Uuid(as_uuid=True), nullable=True)
    comment = Column(Text, nullable=False)

    product_moderation = relationship("ProductModeration", back_populates="field_reports")

    __table_args__ = (
        Index("idx_field_reports_product_moderation_id", "product_moderation_id"),
        Index("idx_field_reports_sku_id", "sku_id"),
    )
