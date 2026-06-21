from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BlockFieldReportRequest(BaseModel):
    field_path: str | None = Field(default=None, max_length=100)
    field_name: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=5000)
    comment: str | None = Field(default=None, max_length=5000)
    severity: str | None = Field(default=None, max_length=50)
    sku_id: UUID | None = None

    @field_validator("field_path", "field_name")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value

    def normalized_field_name(self) -> str:
        return self.field_path or self.field_name or "general"

    def normalized_comment(self) -> str:
        return self.message or self.comment or "Замечание модерации"


class BlockTicketRequest(BaseModel):
    blocking_reason_ids: list[UUID] = Field(..., min_length=1)
    comment: str | None = Field(default=None, max_length=5000)
    field_reports: list[BlockFieldReportRequest] = Field(default_factory=list)


class DeclineFieldName(str, Enum):
    title = "title"
    description = "description"
    product_images = "product_images"
    category = "category"
    sku_name = "sku_name"
    sku_image = "sku_image"
    sku_price = "sku_price"


class DeclineFieldReportRequest(BaseModel):
    field_name: DeclineFieldName
    sku_id: UUID | None = None
    comment: str = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")

    def normalized_field_name(self) -> str:
        return self.field_name.value

    def normalized_comment(self) -> str:
        return self.comment


class DeclineProductRequest(BaseModel):
    blocking_reason_id: UUID
    moderator_comment: str = Field(..., min_length=1, max_length=1000)
    field_reports: list[DeclineFieldReportRequest] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class DeclineProductResponse(BaseModel):
    product_id: UUID
    status: str


class ModerationTicketBlockResponse(BaseModel):
    id: UUID
    product_id: UUID
    seller_id: UUID
    category_id: UUID
    kind: str
    status: str
    queue_priority: int
    assigned_moderator_id: UUID | None = None
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    decision_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
