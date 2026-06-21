from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import MODERATION_IN_REVIEW_TIMEOUT_MINUTES
from src.models.product_moderation import ProductModeration


class QueueService:
    STATUS_PENDING = "PENDING"
    STATUS_IN_REVIEW = "IN_REVIEW"
    QUEUE_PRIORITIES = (1, 2, 3, 4)

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_next_card(
        self,
        *,
        moderator_id: UUID,
        queue_id: int | None = None,
    ) -> ProductModeration | None:
        now = datetime.now(timezone.utc)
        await self._return_expired_reviews(now)

        if await self._moderator_has_active_card(moderator_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MODERATOR_ALREADY_HAS_IN_REVIEW",
                    "message": "Moderator already has an active IN_REVIEW ticket",
                },
            )

        for priority in self._priorities_to_scan(queue_id):
            claimed = await self._claim_oldest_pending_card(
                moderator_id=moderator_id,
                queue_priority=priority,
                now=now,
            )
            if claimed is not None:
                await self.session.commit()
                await self.session.refresh(claimed)
                return claimed

        await self.session.commit()
        return None

    async def _return_expired_reviews(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=MODERATION_IN_REVIEW_TIMEOUT_MINUTES)
        await self.session.execute(
            update(ProductModeration)
            .where(
                ProductModeration.status == self.STATUS_IN_REVIEW,
                or_(
                    ProductModeration.claim_expires_at <= now,
                    and_(
                        ProductModeration.claim_expires_at.is_(None),
                        ProductModeration.claimed_at.is_not(None),
                        ProductModeration.claimed_at <= cutoff,
                    ),
                    and_(
                        ProductModeration.claim_expires_at.is_(None),
                        ProductModeration.claimed_at.is_(None),
                        ProductModeration.date_moderation.is_not(None),
                        ProductModeration.date_moderation <= cutoff,
                    ),
                ),
            )
            .values(
                status=self.STATUS_PENDING,
                assigned_moderator_id=None,
                claimed_at=None,
                claim_expires_at=None,
                date_moderation=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )

    async def _moderator_has_active_card(self, moderator_id: UUID) -> bool:
        result = await self.session.execute(
            select(ProductModeration.id)
            .where(
                ProductModeration.status == self.STATUS_IN_REVIEW,
                ProductModeration.assigned_moderator_id == moderator_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _claim_oldest_pending_card(
        self,
        *,
        moderator_id: UUID,
        queue_priority: int,
        now: datetime,
    ) -> ProductModeration | None:
        result = await self.session.execute(
            select(ProductModeration)
            .where(
                ProductModeration.status == self.STATUS_PENDING,
                ProductModeration.queue_priority == queue_priority,
            )
            .order_by(ProductModeration.updated_at.asc(), ProductModeration.created_at.asc(), ProductModeration.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        candidate = result.scalar_one_or_none()
        if candidate is None:
            return None

        claim_expires_at = now + timedelta(minutes=MODERATION_IN_REVIEW_TIMEOUT_MINUTES)
        update_result = await self.session.execute(
            update(ProductModeration)
            .where(
                ProductModeration.id == candidate.id,
                ProductModeration.status == self.STATUS_PENDING,
            )
            .values(
                status=self.STATUS_IN_REVIEW,
                assigned_moderator_id=moderator_id,
                claimed_at=now,
                claim_expires_at=claim_expires_at,
                date_moderation=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )

        if update_result.rowcount != 1:
            await self.session.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": "TICKET_ALREADY_CLAIMED", "message": "Ticket was already claimed"},
            )

        return candidate

    def _priorities_to_scan(self, queue_id: int | None) -> tuple[int, ...]:
        if queue_id is None:
            return self.QUEUE_PRIORITIES
        return (queue_id,)
