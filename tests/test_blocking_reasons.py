from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.blocking_reason import BlockingReason
from src.models.product_moderation import ProductModeration


async def create_reason(
    test_db: AsyncSession,
    *,
    code: str,
    title: str,
    hard_block: bool = False,
    is_active: bool = True,
    sort_order: int = 0,
) -> BlockingReason:
    reason = BlockingReason(
        id=uuid4(),
        code=code,
        title=title,
        description=f"{title} description",
        hard_block=hard_block,
        is_active=is_active,
        sort_order=sort_order,
    )
    test_db.add(reason)
    await test_db.commit()
    await test_db.refresh(reason)
    return reason


async def get_reason(test_db: AsyncSession, reason_id: UUID) -> BlockingReason:
    result = await test_db.execute(
        select(BlockingReason).where(BlockingReason.id == reason_id)
    )
    reason = result.scalar_one()
    await test_db.refresh(reason)
    return reason


@pytest.mark.asyncio
async def test_list_returns_active_reasons(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    first = await create_reason(
        test_db,
        code="DESCRIPTION_MISMATCH",
        title="Description mismatch",
        sort_order=20,
    )
    second = await create_reason(
        test_db,
        code="IMAGE_MISMATCH",
        title="Image mismatch",
        sort_order=10,
    )

    response = await async_client.get("/api/v1/blocking-reasons")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(second.id),
            "code": "IMAGE_MISMATCH",
            "title": "Image mismatch",
            "hard_block": False,
            "is_active": True,
        },
        {
            "id": str(first.id),
            "code": "DESCRIPTION_MISMATCH",
            "title": "Description mismatch",
            "hard_block": False,
            "is_active": True,
        },
    ]


@pytest.mark.asyncio
async def test_inactive_reasons_not_visible(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    active = await create_reason(
        test_db,
        code="WRONG_CATEGORY",
        title="Wrong category",
    )
    await create_reason(
        test_db,
        code="NOT_ENOUGH_INFO",
        title="Not enough info",
        is_active=False,
    )

    response = await async_client.get("/api/v1/blocking-reasons")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(active.id),
            "code": "WRONG_CATEGORY",
            "title": "Wrong category",
            "hard_block": False,
            "is_active": True,
        }
    ]


@pytest.mark.asyncio
async def test_filter_by_hard_block(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    await create_reason(
        test_db,
        code="INCORRECT_PRICE",
        title="Incorrect price",
        hard_block=False,
    )
    hard_reason = await create_reason(
        test_db,
        code="COUNTERFEIT_PRODUCT",
        title="Counterfeit product",
        hard_block=True,
    )

    response = await async_client.get("/api/v1/blocking-reasons?hard_block=true")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(hard_reason.id),
            "code": "COUNTERFEIT_PRODUCT",
            "title": "Counterfeit product",
            "hard_block": True,
            "is_active": True,
        }
    ]


@pytest.mark.asyncio
async def test_referenced_reason_cannot_be_deleted(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    reason = await create_reason(
        test_db,
        code="COPYRIGHT_VIOLATION",
        title="Copyright violation",
        hard_block=True,
    )
    ticket = ProductModeration(
        id=uuid4(),
        product_id=uuid4(),
        seller_id=uuid4(),
        category_id=uuid4(),
        kind="CREATE",
        status="BLOCKED",
        queue_priority=1,
        blocking_reason_id=reason.id,
    )
    test_db.add(ticket)
    await test_db.commit()

    response = await async_client.delete(f"/api/v1/blocking-reasons/{reason.id}")

    assert response.status_code == 204
    assert response.content == b""

    updated = await get_reason(test_db, reason.id)
    assert updated.is_active is False

    await test_db.refresh(ticket)
    assert ticket.blocking_reason_id == reason.id
