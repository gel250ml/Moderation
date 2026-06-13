from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class B2BEventRequest(BaseModel):
    """Incoming product event from B2B.

    Supports both legacy flow payloads (`event`) and newer envelope payloads
    (`event_type` + `payload`).
    """

    idempotency_key: UUID | None = None
    product_id: UUID | None = None
    seller_id: UUID | None = None
    event: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None
    date: datetime | None = None
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_payload(self):
        if self.product_id is None and self.payload:
            raw_product_id = self.payload.get("product_id")
            if raw_product_id is not None:
                self.product_id = UUID(str(raw_product_id))

        if self.event is None and self.event_type is not None:
            self.event = self.event_type

        if self.event is None:
            raise ValueError("event or event_type is required")
        if self.product_id is None:
            raise ValueError("product_id is required")
        return self

    @property
    def normalized_event(self) -> str:
        return (self.event or self.event_type or "").upper()


class B2BEventResponse(BaseModel):
    status: str = Field(default="accepted")
