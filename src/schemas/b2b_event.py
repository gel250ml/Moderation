from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


_EVENT_ALIASES = {
    "PRODUCT_CREATED": "CREATED",
    "PRODUCT_EDITED": "EDITED",
    "PRODUCT_DELETED": "DELETED",
}


class B2BEventRequest(BaseModel):
    """Incoming product event from B2B.

    Supports both legacy flow payloads (`event`) and newer envelope payloads
    (`event_type` + `payload`). Business code should use normalized fields.
    """

    idempotency_key: str | UUID | None = None
    product_id: UUID | None = None
    seller_id: UUID | None = None
    category_id: UUID | None = None
    queue_priority: int | None = None
    event: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None
    date: datetime | None = None
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_payload(self):
        payload = self.payload or {}

        if self.product_id is None:
            self.product_id = self._uuid_from_payload(payload, "product_id")
        if self.seller_id is None:
            self.seller_id = self._uuid_from_payload(payload, "seller_id")
        if self.category_id is None:
            self.category_id = self._uuid_from_payload(payload, "category_id")
        if self.queue_priority is None and payload.get("queue_priority") is not None:
            self.queue_priority = int(payload["queue_priority"])

        if self.event is None and self.event_type is not None:
            self.event = self.event_type
        if self.occurred_at is None:
            self.occurred_at = self.date

        if self.event is None:
            raise ValueError("event or event_type is required")
        if self.product_id is None:
            raise ValueError("product_id is required")

        return self

    @staticmethod
    def _uuid_from_payload(payload: dict[str, Any], key: str) -> UUID | None:
        raw_value = payload.get(key)
        if raw_value is None:
            return None
        return UUID(str(raw_value))

    @property
    def normalized_event(self) -> str:
        raw_event = (self.event or self.event_type or "").upper()
        return _EVENT_ALIASES.get(raw_event, raw_event)

    @property
    def normalized_idempotency_key(self) -> str:
        if self.idempotency_key is not None:
            return str(self.idempotency_key)

        # Legacy contract originally allowed dedupe by (product_id, date). Keep a
        # deterministic fallback so old clients are still safe under retries.
        occurred = self.occurred_at.isoformat() if self.occurred_at else "no-date"
        return f"{self.product_id}:{self.normalized_event}:{occurred}"


class B2BEventResponse(BaseModel):
    status: str = Field(default="accepted")
