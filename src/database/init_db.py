from uuid import UUID

from sqlalchemy import select

from src.database.session import async_session_maker, engine
from src.database.base import Base

# ВАЖНО: импортируем модели, чтобы они зарегистрировались в metadata
from src.models import *
from src.models.blocking_reason import BlockingReason


HARD_BLOCK_REASON_ID = UUID("b8c9d0e1-2345-6789-f012-901234567890")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await seed_blocking_reasons()


async def seed_blocking_reasons() -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(BlockingReason).where(BlockingReason.id == HARD_BLOCK_REASON_ID)
        )
        reason = result.scalar_one_or_none()
        if reason is None:
            session.add(
                BlockingReason(
                    id=HARD_BLOCK_REASON_ID,
                    title="Контрафактный товар",
                    description="Жёсткая блокировка: контрафактный товар",
                    hard_block=True,
                )
            )
            await session.commit()
