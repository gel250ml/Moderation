from uuid import UUID

from sqlalchemy import select, text

from src.database.session import async_session_maker, engine
from src.database.base import Base

# ВАЖНО: импортируем модели, чтобы они зарегистрировались в metadata
from src.models import *
from src.models.blocking_reason import BlockingReason


BLOCKING_REASON_SEED = [
    {
        "id": UUID("a7b8c9d0-1234-5678-ef01-890123456789"),
        "title": "Описание не соответствует товару",
        "description": "Мягкая блокировка: описание не соответствует товару",
        "hard_block": False,
        "is_active": True,
        "sort_order": 10,
    },
    {
        "id": UUID("b8c9d0e1-2345-6789-f012-901234567890"),
        "title": "Изображение не соответствует товару",
        "description": "Мягкая блокировка: изображение не соответствует товару",
        "hard_block": False,
        "is_active": True,
        "sort_order": 20,
    },
    {
        "id": UUID("c9d0e1f2-3456-7890-0123-012345678901"),
        "title": "Некорректная категория товара",
        "description": "Мягкая блокировка: некорректная категория товара",
        "hard_block": False,
        "is_active": True,
        "sort_order": 30,
    },
    {
        "id": UUID("d0e1f2a3-4567-8901-1234-123456789012"),
        "title": "Недостаточно информации о товаре",
        "description": "Мягкая блокировка: недостаточно информации о товаре",
        "hard_block": False,
        "is_active": True,
        "sort_order": 40,
    },
    {
        "id": UUID("e1f2a3b4-5678-9012-2345-234567890123"),
        "title": "Нецензурные или оскорбительные материалы",
        "description": "Мягкая блокировка: нецензурные или оскорбительные материалы",
        "hard_block": False,
        "is_active": True,
        "sort_order": 50,
    },
    {
        "id": UUID("f2a3b4c5-6789-0123-3456-345678901234"),
        "title": "Дублирование существующего товара",
        "description": "Мягкая блокировка: дублирование существующего товара",
        "hard_block": False,
        "is_active": True,
        "sort_order": 60,
    },
    {
        "id": UUID("a3b4c5d6-7890-1234-4567-456789012345"),
        "title": "Некорректная цена",
        "description": "Мягкая блокировка: некорректная цена",
        "hard_block": False,
        "is_active": True,
        "sort_order": 70,
    },
    {
        "id": UUID("b4c5d6e7-8901-2345-5678-567890123456"),
        "title": "Контрафактный товар",
        "description": "Жёсткая блокировка: контрафактный товар",
        "hard_block": True,
        "is_active": True,
        "sort_order": 80,
    },
    {
        "id": UUID("c5d6e7f8-9012-3456-6789-678901234567"),
        "title": "Товар запрещён к продаже на территории РФ",
        "description": "Жёсткая блокировка: товар запрещён к продаже на территории РФ",
        "hard_block": True,
        "is_active": True,
        "sort_order": 90,
    },
    {
        "id": UUID("d6e7f8a9-0123-4567-7890-789012345678"),
        "title": "Товар нарушает авторские права",
        "description": "Жёсткая блокировка: товар нарушает авторские права",
        "hard_block": True,
        "is_active": True,
        "sort_order": 100,
    },
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_schema_compatibility(conn)

    await seed_blocking_reasons()


async def _ensure_schema_compatibility(conn) -> None:
    """Small compatibility layer for existing dev databases without migrations."""
    if engine.dialect.name != "postgresql":
        return

    await conn.execute(
        text(
            """
            ALTER TABLE blocking_reasons
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_product_moderation_blocking_reason_id'
                ) THEN
                    ALTER TABLE product_moderation
                    ADD CONSTRAINT fk_product_moderation_blocking_reason_id
                    FOREIGN KEY (blocking_reason_id)
                    REFERENCES blocking_reasons(id)
                    ON DELETE RESTRICT;
                END IF;
            END $$;
            """
        )
    )


async def seed_blocking_reasons() -> None:
    async with async_session_maker() as session:
        for seed in BLOCKING_REASON_SEED:
            result = await session.execute(
                select(BlockingReason).where(BlockingReason.id == seed["id"])
            )
            reason = result.scalar_one_or_none()
            if reason is None:
                session.add(BlockingReason(**seed))
                continue

            reason.title = seed["title"]
            reason.description = seed["description"]
            reason.hard_block = seed["hard_block"]
            reason.is_active = seed["is_active"]
            reason.sort_order = seed["sort_order"]
            session.add(reason)

        await session.commit()
