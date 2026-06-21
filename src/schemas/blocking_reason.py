from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BlockingReasonResponse(BaseModel):
    id: UUID
    code: str
    title: str
    hard_block: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class BlockingReasonAdminResponse(BlockingReasonResponse):
    description: str | None = None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class BlockingReasonCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Z_]+$")
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    hard_block: bool
    is_active: bool = True
    sort_order: int = 0


class BlockingReasonUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Z_]+$")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    hard_block: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
