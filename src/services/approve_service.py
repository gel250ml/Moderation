import logging
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration
from src.schemas.approve import ApproveProductResponse, ModerationTicketResponse
from src.services.b2b_client import (
    B2BClient,
    B2BClientError,
    B2BProductNotFoundError,
    B2BProductUnavailableError,
)

logger = logging.getLogger(__name__)


class ApproveService:
    STATUS_IN_REVIEW = "IN_REVIEW"
    STATUS_MODERATED = "MODERATED"
    STATUS_HARD_BLOCKED = "HARD_BLOCKED"

    def __init__(self, session: AsyncSession, b2b_client: B2BClient | None = None):
        self.session = session
        self.b2b_client = b2b_client or B2BClient()

    async def approve_by_ticket_id(
        self,
        *,
        ticket_id: UUID,
        moderator_id: UUID,
        comment: str | None,
    ) -> ModerationTicketResponse:
        ticket = await self._get_ticket_by_id(ticket_id)
        await self._approve(ticket=ticket, moderator_id=moderator_id, comment=comment)
        return ModerationTicketResponse.model_validate(ticket)

    async def approve_by_product_id(
        self,
        *,
        product_id: UUID,
        moderator_id: UUID,
        comment: str | None,
    ) -> ApproveProductResponse:
        ticket = await self._get_ticket_by_product_id(product_id)
        await self._approve(ticket=ticket, moderator_id=moderator_id, comment=comment)
        return ApproveProductResponse(product_id=ticket.product_id, status=ticket.status)

    async def _approve(
        self,
        *,
        ticket: ProductModeration,
        moderator_id: UUID,
        comment: str | None,
    ) -> None:
        self._validate_ticket(ticket, moderator_id)

        try:
            await self.b2b_client.ensure_product_has_skus(ticket.product_id)
        except B2BProductNotFoundError:
            raise NotFoundException("Product not found")
        except B2BProductUnavailableError as exc:
            raise ConflictException(str(exc))
        except B2BClientError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "B2B_UNAVAILABLE", "message": str(exc)},
            )

        now = datetime.now(timezone.utc)
        ticket.status = self.STATUS_MODERATED
        ticket.decision_at = now
        ticket.date_moderation = now
        ticket.moderator_comment = comment
        ticket.blocking_reason_id = None
        self.session.add(ticket)
        await self.session.execute(
            delete(ModerationFieldReport).where(
                ModerationFieldReport.product_moderation_id == ticket.id
            )
        )

        idempotency_key = self._event_idempotency_key(ticket.id)
        try:
            await self.b2b_client.send_moderated_event(
                product_id=ticket.product_id,
                ticket_idempotency_key=idempotency_key,
                moderator_id=moderator_id,
                moderator_comment=comment,
            )
        except B2BClientError as exc:
            logger.exception("Failed to deliver MODERATED event for ticket %s", ticket.id)
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

    def _validate_ticket(self, ticket: ProductModeration, moderator_id: UUID) -> None:
        if ticket.status == self.STATUS_HARD_BLOCKED:
            raise ForbiddenException("Product is permanently blocked")
        if ticket.status != self.STATUS_IN_REVIEW:
            raise ConflictException("Product is not in review status")
        if ticket.assigned_moderator_id != moderator_id:
            raise ForbiddenException("This moderation card is not assigned to you")

    @staticmethod
    def _event_idempotency_key(ticket_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"moderation:ticket:{ticket_id}:moderated")
