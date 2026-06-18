from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationException
from src.models.moderation_field_report import ModerationFieldReport
from src.models.processed_event import ProcessedEvent
from src.models.product_moderation import ProductModeration
from src.schemas.b2b_event import B2BEventRequest
from src.services.b2b_client import B2BClient, B2BClientError


class B2BEventService:
    SENDER_SERVICE = "b2b"

    STATUS_PENDING = "PENDING"
    STATUS_IN_REVIEW = "IN_REVIEW"
    STATUS_BLOCKED = "BLOCKED"
    STATUS_APPROVED = "APPROVED"
    STATUS_MODERATED = "MODERATED"
    STATUS_HARD_BLOCKED = "HARD_BLOCKED"

    KIND_CREATE = "CREATE"
    KIND_EDIT = "EDIT"

    CREATED_EVENTS = {"CREATED"}
    EDITED_EVENTS = {"EDITED"}
    DELETED_EVENTS = {"DELETED"}

    def __init__(self, session: AsyncSession, b2b_client: B2BClient | None = None):
        self.session = session
        self.b2b_client = b2b_client or B2BClient()

    async def apply(self, data: B2BEventRequest) -> None:
        event = data.normalized_event
        if event in self.CREATED_EVENTS:
            await self._apply_created(data)
            return
        if event in self.EDITED_EVENTS:
            await self._apply_edited(data)
            return
        if event in self.DELETED_EVENTS:
            await self._apply_deleted(data)
            return
        raise ValidationException("Unsupported product event")

    async def _apply_created(self, data: B2BEventRequest) -> None:
        if await self._already_processed(data):
            return

        existing_ticket = await self._get_latest_ticket(data.product_id)  # type: ignore[arg-type]
        if existing_ticket is not None:
            if existing_ticket.status == self.STATUS_HARD_BLOCKED:
                self._mark_processed(data)
                await self.session.commit()
                return
            raise ValidationException("Product moderation card already exists")

        snapshot = await self._get_product_snapshot(data.product_id)  # type: ignore[arg-type]
        seller_id = data.seller_id or self._uuid_from_snapshot(snapshot, "seller_id")
        category_id = data.category_id or self._uuid_from_snapshot(snapshot, "category_id")

        if seller_id is None:
            raise HTTPException(
                status_code=500,
                detail={"code": "B2B_INVALID_RESPONSE", "message": "B2B product snapshot has no seller_id"},
            )
        if category_id is None:
            raise HTTPException(
                status_code=500,
                detail={"code": "B2B_INVALID_RESPONSE", "message": "B2B product snapshot has no category_id"},
            )

        ticket = ProductModeration(
            product_id=data.product_id,
            seller_id=seller_id,
            category_id=category_id,
            kind=self.KIND_CREATE,
            status=self.STATUS_PENDING,
            queue_priority=data.queue_priority or 1,
            json_before=None,
            json_after=snapshot,
            source_event_at=data.occurred_at,
        )
        self.session.add(ticket)
        self._mark_processed(data)
        await self.session.commit()

    async def _apply_edited(self, data: B2BEventRequest) -> None:
        if await self._already_processed(data):
            return

        ticket = await self._get_latest_ticket(data.product_id)  # type: ignore[arg-type]
        if ticket is None:
            raise ValidationException("Product moderation card not found")

        if ticket.status == self.STATUS_HARD_BLOCKED:
            self._mark_processed(data)
            await self.session.commit()
            return

        old_status = ticket.status
        old_priority = ticket.queue_priority
        snapshot = await self._get_product_snapshot(data.product_id)  # type: ignore[arg-type]

        ticket.json_before = ticket.json_after
        ticket.json_after = snapshot
        ticket.kind = self.KIND_EDIT
        ticket.status = self.STATUS_PENDING
        ticket.queue_priority = self._queue_priority_for_edit(old_status, old_priority, snapshot)
        ticket.assigned_moderator_id = None
        ticket.claimed_at = None
        ticket.claim_expires_at = None
        ticket.decision_at = None
        ticket.date_moderation = None
        ticket.blocking_reason_id = None
        ticket.moderator_comment = None
        ticket.source_event_at = data.occurred_at
        self.session.add(ticket)

        await self.session.execute(
            delete(ModerationFieldReport).where(ModerationFieldReport.product_moderation_id == ticket.id)
        )
        self._mark_processed(data)
        await self.session.commit()
        await self.session.refresh(ticket)

    async def _apply_deleted(self, data: B2BEventRequest) -> None:
        if await self._already_processed(data):
            return

        ticket_ids_result = await self.session.execute(
            select(ProductModeration.id).where(ProductModeration.product_id == data.product_id)
        )
        ticket_ids = list(ticket_ids_result.scalars().all())
        if ticket_ids:
            await self.session.execute(
                delete(ModerationFieldReport).where(
                    ModerationFieldReport.product_moderation_id.in_(ticket_ids)
                )
            )
        await self.session.execute(
            delete(ProductModeration).where(ProductModeration.product_id == data.product_id)
        )
        self._mark_processed(data)
        await self.session.commit()

    async def _get_product_snapshot(self, product_id: UUID) -> dict:
        try:
            return await self.b2b_client.get_product(product_id)
        except B2BClientError as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "B2B_UNAVAILABLE", "message": "Failed to fetch product from B2B"},
            ) from exc

    async def _already_processed(self, data: B2BEventRequest) -> bool:
        result = await self.session.execute(
            select(ProcessedEvent.id).where(
                ProcessedEvent.sender_service == self.SENDER_SERVICE,
                ProcessedEvent.idempotency_key == data.normalized_idempotency_key,
            )
        )
        return result.scalar_one_or_none() is not None

    def _mark_processed(self, data: B2BEventRequest) -> None:
        self.session.add(
            ProcessedEvent(
                sender_service=self.SENDER_SERVICE,
                idempotency_key=data.normalized_idempotency_key,
            )
        )

    async def _get_latest_ticket(self, product_id: UUID | None) -> ProductModeration | None:
        if product_id is None:
            return None
        result = await self.session.execute(
            select(ProductModeration)
            .where(ProductModeration.product_id == product_id)
            .order_by(desc(ProductModeration.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _queue_priority_for_edit(self, old_status: str, old_priority: int, snapshot: dict) -> int:
        if old_status == self.STATUS_BLOCKED:
            return 2
        if old_status in {self.STATUS_MODERATED, self.STATUS_APPROVED}:
            return 3 if self._total_active_quantity(snapshot) > 0 else 4
        return old_priority

    @staticmethod
    def _total_active_quantity(snapshot: dict) -> int:
        if snapshot.get("total_active_quantity") is not None:
            try:
                return int(snapshot["total_active_quantity"])
            except (TypeError, ValueError):
                return 0

        total = 0
        for sku in snapshot.get("skus") or []:
            if not isinstance(sku, dict):
                continue
            raw_value = sku.get("active_quantity", sku.get("quantity", sku.get("stock_quantity", 0)))
            try:
                total += int(raw_value or 0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _uuid_from_snapshot(snapshot: dict, key: str) -> UUID | None:
        raw_value = snapshot.get(key)
        if raw_value is None:
            return None
        return UUID(str(raw_value))
