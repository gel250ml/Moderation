from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.product_moderation import ProductModeration


class QueueClaimRequest(BaseModel):
    queue_priority: int | None = Field(default=None, ge=1, le=4)

    model_config = ConfigDict(extra="forbid")


class TicketResponse(BaseModel):
    id: UUID
    product_id: UUID
    seller_id: UUID
    category_id: UUID | None = None
    kind: str
    status: str
    queue_priority: int
    json_before: dict[str, Any] | None = None
    json_after: dict[str, Any] | None = None
    blocking_history: dict[str, Any] | None = None
    assigned_moderator_id: UUID | None = None
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    decision_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_ticket(cls, ticket: ProductModeration) -> "TicketResponse":
        return cls(
            id=ticket.id,
            product_id=ticket.product_id,
            seller_id=ticket.seller_id,
            category_id=ticket.category_id,
            kind=ticket.kind,
            status=ticket.status,
            queue_priority=ticket.queue_priority,
            json_before=ticket.json_before,
            json_after=ticket.json_after,
            blocking_history=cls._blocking_history_from_ticket(ticket),
            assigned_moderator_id=ticket.assigned_moderator_id,
            claimed_at=ticket.claimed_at,
            claim_expires_at=ticket.claim_expires_at,
            decision_at=ticket.decision_at,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )

    @staticmethod
    def _blocking_history_from_ticket(ticket: ProductModeration) -> dict[str, Any] | None:
        before = ticket.json_before or {}
        if not isinstance(before, dict):
            return None

        existing_history = before.get("blocking_history")
        if isinstance(existing_history, dict):
            return existing_history

        blocking_reason = before.get("blocking_reason")
        field_reports = before.get("field_reports") or []
        moderator_comment = before.get("moderator_comment")
        date_blocked = before.get("date_blocked") or before.get("blocked_at")

        if isinstance(blocking_reason, dict):
            moderator_comment = moderator_comment or blocking_reason.get("comment")
            compact_reason = {
                key: value
                for key, value in blocking_reason.items()
                if key in {"id", "title", "code", "description"} and value is not None
            }
        else:
            compact_reason = None

        if compact_reason is None and not field_reports and moderator_comment is None and date_blocked is None:
            return None

        return {
            "blocking_reason": compact_reason,
            "moderator_comment": moderator_comment,
            "field_reports": field_reports,
            "date_blocked": date_blocked,
        }


# Backward-compatible aliases for internal imports in older local tests/code.
GetNextQueueRequest = QueueClaimRequest
GetNextQueueResponse = TicketResponse
