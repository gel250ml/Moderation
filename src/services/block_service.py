import logging
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, ForbiddenException, NotFoundException, ValidationException
from src.models.blocking_reason import BlockingReason
from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration
from src.schemas.block import (
    BlockFieldReportRequest,
    DeclineProductResponse,
    ModerationTicketBlockResponse,
)
from src.services.b2b_client import B2BClient, B2BClientError

logger = logging.getLogger(__name__)


class BlockService:
    STATUS_IN_REVIEW = "IN_REVIEW"
    STATUS_BLOCKED = "BLOCKED"
    STATUS_HARD_BLOCKED = "HARD_BLOCKED"

    def __init__(self, session: AsyncSession, b2b_client: B2BClient | None = None):
        self.session = session
        self.b2b_client = b2b_client or B2BClient()

    async def block_by_ticket_id(
        self,
        *,
        ticket_id: UUID,
        moderator_id: UUID,
        blocking_reason_ids: list[UUID],
        comment: str | None,
        field_reports: list[BlockFieldReportRequest],
    ) -> ModerationTicketBlockResponse:
        ticket = await self._get_ticket_by_id(ticket_id)
        await self._block(
            ticket=ticket,
            moderator_id=moderator_id,
            blocking_reason_ids=blocking_reason_ids,
            comment=comment,
            field_reports=field_reports,
        )
        return ModerationTicketBlockResponse.model_validate(ticket)

    async def decline_by_product_id(
        self,
        *,
        product_id: UUID,
        moderator_id: UUID,
        blocking_reason_id: UUID,
        moderator_comment: str | None,
        field_reports: list[BlockFieldReportRequest],
    ) -> DeclineProductResponse:
        ticket = await self._get_ticket_by_product_id(product_id)
        await self._block(
            ticket=ticket,
            moderator_id=moderator_id,
            blocking_reason_ids=[blocking_reason_id],
            comment=moderator_comment,
            field_reports=field_reports,
        )
        return DeclineProductResponse(product_id=ticket.product_id, status=ticket.status)

    async def _block(
        self,
        *,
        ticket: ProductModeration,
        moderator_id: UUID,
        blocking_reason_ids: list[UUID],
        comment: str | None,
        field_reports: list[BlockFieldReportRequest],
    ) -> None:
        self._validate_ticket(ticket, moderator_id)
        reasons = await self._get_blocking_reasons(blocking_reason_ids)
        primary_reason = reasons[0]
        hard_block = any(reason.hard_block for reason in reasons)
        next_status = self.STATUS_HARD_BLOCKED if hard_block else self.STATUS_BLOCKED

        now = datetime.now(timezone.utc)
        ticket.status = next_status
        ticket.decision_at = now
        ticket.date_moderation = now
        ticket.blocking_reason_id = primary_reason.id
        ticket.moderator_comment = comment
        self.session.add(ticket)

        await self.session.execute(
            delete(ModerationFieldReport).where(
                ModerationFieldReport.product_moderation_id == ticket.id
            )
        )

        db_reports = self._to_db_field_reports(ticket.id, field_reports)
        for report in db_reports:
            self.session.add(report)

        idempotency_key = self._event_idempotency_key(ticket.id, hard_block)
        try:
            await self.b2b_client.send_blocked_event(
                product_id=ticket.product_id,
                ticket_idempotency_key=idempotency_key,
                hard_block=hard_block,
                blocking_reason_id=primary_reason.id,
                blocking_reason_title=primary_reason.title,
                moderator_comment=comment,
                field_reports=self._to_b2b_field_reports(field_reports),
            )
        except B2BClientError as exc:
            logger.exception("Failed to deliver BLOCKED event for ticket %s", ticket.id)
            await self.session.rollback()
            raise HTTPException(
                status_code=500,
                detail={"code": "B2B_EVENT_FAILED", "message": "Failed to deliver moderation event to B2B"},
            ) from exc

        await self.session.commit()
        await self.session.refresh(ticket)

    async def _get_ticket_by_id(self, ticket_id: UUID) -> ProductModeration:
        result = await self.session.execute(
            select(ProductModeration).where(ProductModeration.id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise NotFoundException("Product not found in moderation queue")
        return ticket

    async def _get_ticket_by_product_id(self, product_id: UUID) -> ProductModeration:
        result = await self.session.execute(
            select(ProductModeration)
            .where(ProductModeration.product_id == product_id)
            .order_by(desc(ProductModeration.created_at))
            .limit(1)
        )
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise NotFoundException("Product not found in moderation queue")
        return ticket

    async def _get_blocking_reasons(self, reason_ids: list[UUID]) -> list[BlockingReason]:
        if not reason_ids:
            raise ValidationException("blocking_reason_ids must not be empty")

        unique_reason_ids = list(dict.fromkeys(reason_ids))
        result = await self.session.execute(
            select(BlockingReason).where(
                BlockingReason.id.in_(unique_reason_ids),
                BlockingReason.is_active.is_(True),
            )
        )
        found_by_id = {reason.id: reason for reason in result.scalars().all()}
        missing = [reason_id for reason_id in unique_reason_ids if reason_id not in found_by_id]
        if missing:
            raise ValidationException("Blocking reason not found or inactive")
        return [found_by_id[reason_id] for reason_id in unique_reason_ids]

    def _validate_ticket(self, ticket: ProductModeration, moderator_id: UUID) -> None:
        if ticket.status == self.STATUS_HARD_BLOCKED:
            raise ForbiddenException("Product is permanently blocked")
        if ticket.status != self.STATUS_IN_REVIEW:
            raise ConflictException("Product is not in review status")
        if ticket.assigned_moderator_id != moderator_id:
            raise ForbiddenException("This moderation card is not assigned to you")

    @staticmethod
    def _to_db_field_reports(
        ticket_id: UUID,
        field_reports: list[BlockFieldReportRequest],
    ) -> list[ModerationFieldReport]:
        return [
            ModerationFieldReport(
                product_moderation_id=ticket_id,
                field_name=report.normalized_field_name(),
                sku_id=report.sku_id,
                comment=report.normalized_comment(),
            )
            for report in field_reports
        ]

    @staticmethod
    def _to_b2b_field_reports(field_reports: list[BlockFieldReportRequest]) -> list[dict]:
        return [
            {
                "field_name": report.normalized_field_name(),
                "sku_id": str(report.sku_id) if report.sku_id is not None else None,
                "comment": report.normalized_comment(),
            }
            for report in field_reports
        ]

    @staticmethod
    def _event_idempotency_key(ticket_id: UUID, hard_block: bool) -> UUID:
        block_type = "hard_blocked" if hard_block else "blocked"
        return uuid5(NAMESPACE_URL, f"moderation:ticket:{ticket_id}:{block_type}")
