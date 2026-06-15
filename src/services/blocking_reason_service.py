from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException
from src.models.blocking_reason import BlockingReason
from src.models.product_moderation import ProductModeration
from src.schemas.blocking_reason import (
    BlockingReasonCreateRequest,
    BlockingReasonUpdateRequest,
)


class BlockingReasonService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_reasons(
        self,
        *,
        hard_block: bool | None = None,
        is_active: bool | None = True,
    ) -> list[BlockingReason]:
        stmt = select(BlockingReason)
        if hard_block is not None:
            stmt = stmt.where(BlockingReason.hard_block == hard_block)
        if is_active is not None:
            stmt = stmt.where(BlockingReason.is_active == is_active)

        stmt = stmt.order_by(
            BlockingReason.sort_order.asc(),
            BlockingReason.hard_block.asc(),
            BlockingReason.title.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_reason(self, reason_id: UUID) -> BlockingReason:
        reason = await self.session.get(BlockingReason, reason_id)
        if reason is None:
            raise NotFoundException("Blocking reason not found")
        return reason

    async def create_reason(self, data: BlockingReasonCreateRequest) -> BlockingReason:
        reason = BlockingReason(**data.model_dump())
        self.session.add(reason)
        await self.session.commit()
        await self.session.refresh(reason)
        return reason

    async def update_reason(
        self,
        reason_id: UUID,
        data: BlockingReasonUpdateRequest,
    ) -> BlockingReason:
        reason = await self.get_reason(reason_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(reason, field, value)

        self.session.add(reason)
        await self.session.commit()
        await self.session.refresh(reason)
        return reason

    async def deactivate_reason(self, reason_id: UUID) -> BlockingReason:
        reason = await self.get_reason(reason_id)
        reason.is_active = False
        self.session.add(reason)
        await self.session.commit()
        await self.session.refresh(reason)
        return reason

    async def assert_reason_can_be_physically_deleted(self, reason_id: UUID) -> None:
        result = await self.session.execute(
            select(func.count(ProductModeration.id)).where(
                ProductModeration.blocking_reason_id == reason_id
            )
        )
        referenced_count = result.scalar_one()
        if referenced_count:
            raise ConflictException(
                "Blocking reason is referenced by moderation history and cannot be physically deleted"
            )
