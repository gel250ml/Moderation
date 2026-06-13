from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration
from src.schemas.b2b_event import B2BEventRequest


class B2BEventService:
    STATUS_HARD_BLOCKED = "HARD_BLOCKED"
    EDITED_EVENTS = {"EDITED", "PRODUCT_EDITED"}
    DELETED_EVENTS = {"DELETED", "PRODUCT_DELETED"}

    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply(self, data: B2BEventRequest) -> None:
        event = data.normalized_event
        if event in self.EDITED_EVENTS:
            await self._apply_edited(data)
            return
        if event in self.DELETED_EVENTS:
            await self._apply_deleted(data)
            return
        return

    async def _apply_edited(self, data: B2BEventRequest) -> None:
        ticket = await self._get_latest_ticket(data.product_id)  # type: ignore[arg-type]
        if ticket is None:
            return

        if ticket.status == self.STATUS_HARD_BLOCKED:
            return

        # Existing project has no seller edit queue flow yet. Keep this event safe
        # and idempotent instead of inventing a new status transition.
        return

    async def _apply_deleted(self, data: B2BEventRequest) -> None:
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
        await self.session.commit()

    async def _get_latest_ticket(self, product_id):
        result = await self.session.execute(
            select(ProductModeration)
            .where(ProductModeration.product_id == product_id)
            .order_by(desc(ProductModeration.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()
