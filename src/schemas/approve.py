from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApproveTicketRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=5000)


class ModerationTicketResponse(BaseModel):
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
