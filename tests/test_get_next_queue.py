import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product_moderation import ProductModeration

pytestmark = pytest.mark.asyncio


def create_moderator_jwt(moderator_id: UUID) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"moderator_id": str(moderator_id), "sub": str(moderator_id)}

    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"signature").decode().rstrip("=")

    return f"{header_b64}.{payload_b64}.{signature}"


def auth_headers(moderator_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_moderator_jwt(moderator_id)}"}


def product_snapshot(product_id: UUID, title: str = "Product") -> dict:
    return {
        "id": str(product_id),
        "title": title,
        "description": "Product for moderation",
        "status": "ON_MODERATION",
        "deleted": False,
        "blocked": False,
        "category": {"id": str(uuid4()), "name": "Electronics"},
        "images": [{"url": "/s3/product.jpg", "ordering": 0}],
        "characteristics": [{"name": "Brand", "value": "Neo"}],
        "skus": [{"id": str(uuid4()), "name": "base", "price": 1000, "active_quantity": 3}],
        "blocking_reason": None,
        "field_reports": [],
    }


async def create_ticket(
    test_db: AsyncSession,
    *,
    status: str = "PENDING",
    queue_priority: int = 1,
    updated_at: datetime | None = None,
    created_at: datetime | None = None,
    assigned_moderator_id: UUID | None = None,
    claimed_at: datetime | None = None,
    claim_expires_at: datetime | None = None,
    json_before: dict | None = None,
) -> ProductModeration:
    product_id = uuid4()
    now = datetime.now(timezone.utc)
    ticket = ProductModeration(
        id=uuid4(),
        product_id=product_id,
        seller_id=uuid4(),
        category_id=uuid4(),
        kind="CREATE",
        status=status,
        queue_priority=queue_priority,
        json_before=json_before,
        json_after=product_snapshot(product_id),
        assigned_moderator_id=assigned_moderator_id,
        claimed_at=claimed_at,
        claim_expires_at=claim_expires_at,
        date_moderation=claimed_at,
        created_at=created_at or updated_at or now,
        updated_at=updated_at or created_at or now,
    )
    test_db.add(ticket)
    await test_db.commit()
    await test_db.refresh(ticket)
    return ticket


async def get_ticket(test_db: AsyncSession, ticket_id: UUID) -> ProductModeration:
    result = await test_db.execute(select(ProductModeration).where(ProductModeration.id == ticket_id))
    ticket = result.scalar_one()
    await test_db.refresh(ticket)
    return ticket


async def test_next_returns_oldest_pending(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    newer = await create_ticket(
        test_db,
        updated_at=datetime(2026, 3, 15, 14, 31, tzinfo=timezone.utc),
    )
    oldest = await create_ticket(
        test_db,
        updated_at=datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc),
    )

    response = await async_client.post(
        "/api/v1/queue/claim",
        headers=auth_headers(moderator_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(oldest.id)
    assert body["product_id"] == str(oldest.product_id)
    assert body["status"] == "IN_REVIEW"
    assert body["queue_priority"] == 1
    assert body["assigned_moderator_id"] == str(moderator_id)
    assert body["claimed_at"] is not None
    assert body["claim_expires_at"] is not None

    updated_oldest = await get_ticket(test_db, oldest.id)
    updated_newer = await get_ticket(test_db, newer.id)
    assert updated_oldest.status == "IN_REVIEW"
    assert updated_oldest.assigned_moderator_id == moderator_id
    assert updated_newer.status == "PENDING"


async def test_concurrent_two_moderators_get_different_cards(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    first = await create_ticket(
        test_db,
        updated_at=datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc),
    )
    second = await create_ticket(
        test_db,
        updated_at=datetime(2026, 3, 15, 14, 31, tzinfo=timezone.utc),
    )
    first_moderator = uuid4()
    second_moderator = uuid4()

    first_response = await async_client.post(
        "/api/v1/queue/claim",
        headers=auth_headers(first_moderator),
    )
    second_response = await async_client.post(
        "/api/v1/queue/claim",
        headers=auth_headers(second_moderator),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    claimed_ids = {
        first_response.json()["id"],
        second_response.json()["id"],
    }
    assert claimed_ids == {str(first.id), str(second.id)}
    assert len(claimed_ids) == 2


async def test_empty_queue_returns_204(async_client: httpx.AsyncClient):
    response = await async_client.post(
        "/api/v1/queue/claim",
        headers=auth_headers(uuid4()),
    )

    assert response.status_code == 204
    assert response.content == b""


async def test_moderator_already_has_in_review_returns_409(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    now = datetime.now(timezone.utc)
    active = await create_ticket(
        test_db,
        status="IN_REVIEW",
        assigned_moderator_id=moderator_id,
        claimed_at=now,
        claim_expires_at=now + timedelta(minutes=30),
    )
    pending = await create_ticket(test_db)

    response = await async_client.post(
        "/api/v1/queue/claim",
        headers=auth_headers(moderator_id),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "MODERATOR_ALREADY_HAS_IN_REVIEW"
    assert (await get_ticket(test_db, active.id)).status == "IN_REVIEW"
    assert (await get_ticket(test_db, pending.id)).status == "PENDING"


async def test_invalid_queue_id_returns_400(async_client: httpx.AsyncClient):
    response = await async_client.post(
        "/api/v1/queue/claim",
        json={"queue_priority": 5},
        headers=auth_headers(uuid4()),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_expired_in_review_returns_to_queue(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    new_moderator_id = uuid4()
    stale_moderator_id = uuid4()
    stale_claimed_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    stale_ticket = await create_ticket(
        test_db,
        status="IN_REVIEW",
        assigned_moderator_id=stale_moderator_id,
        claimed_at=stale_claimed_at,
        claim_expires_at=stale_claimed_at + timedelta(minutes=30),
        updated_at=datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc),
    )

    response = await async_client.post(
        "/api/v1/queue/claim",
        headers=auth_headers(new_moderator_id),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(stale_ticket.id)
    updated = await get_ticket(test_db, stale_ticket.id)
    assert updated.status == "IN_REVIEW"
    assert updated.assigned_moderator_id == new_moderator_id
    assert updated.claim_expires_at is not None
