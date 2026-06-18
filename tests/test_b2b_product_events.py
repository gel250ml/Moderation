from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration
from src.services.b2b_client import B2BClient

pytestmark = pytest.mark.asyncio

SERVICE_KEY = "b2b-test-key"


def auth_headers() -> dict[str, str]:
    return {"X-Service-Key": SERVICE_KEY}


def snapshot(
    *,
    product_id: UUID,
    seller_id: UUID,
    category_id: UUID | None = None,
    total_active_quantity: int = 5,
    title: str = "Product snapshot",
) -> dict:
    return {
        "id": str(product_id),
        "product_id": str(product_id),
        "seller_id": str(seller_id),
        "category_id": str(category_id or uuid4()),
        "title": title,
        "total_active_quantity": total_active_quantity,
        "skus": [{"id": str(uuid4()), "active_quantity": total_active_quantity}],
    }


async def get_ticket_by_product(test_db: AsyncSession, product_id: UUID) -> ProductModeration | None:
    result = await test_db.execute(
        select(ProductModeration).where(ProductModeration.product_id == product_id)
    )
    return result.scalar_one_or_none()


async def count_tickets(test_db: AsyncSession, product_id: UUID) -> int:
    result = await test_db.execute(
        select(func.count(ProductModeration.id)).where(ProductModeration.product_id == product_id)
    )
    return result.scalar_one()


async def test_created_pending(async_client, test_db: AsyncSession, monkeypatch):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", SERVICE_KEY)
    product_id = uuid4()
    seller_id = uuid4()
    category_id = uuid4()
    product_snapshot = snapshot(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        title="Created product",
    )

    async def fake_get_product(self: B2BClient, requested_product_id: UUID) -> dict:
        assert requested_product_id == product_id
        return product_snapshot

    monkeypatch.setattr("src.services.b2b_client.B2BClient.get_product", fake_get_product)

    response = await async_client.post(
        "/api/v1/events/product",
        json={
            "event": "CREATED",
            "idempotency_key": str(uuid4()),
            "product_id": str(product_id),
            "seller_id": str(seller_id),
            "date": datetime.now(timezone.utc).isoformat(),
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    ticket = await get_ticket_by_product(test_db, product_id)
    assert ticket is not None
    assert ticket.status == "PENDING"
    assert ticket.kind == "CREATE"
    assert ticket.queue_priority == 1
    assert ticket.seller_id == seller_id
    assert ticket.category_id == category_id
    assert ticket.json_before is None
    assert ticket.json_after == product_snapshot


async def test_edited_returns_to_review(async_client, test_db: AsyncSession, monkeypatch):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", SERVICE_KEY)
    product_id = uuid4()
    seller_id = uuid4()
    category_id = uuid4()
    old_snapshot = snapshot(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        total_active_quantity=0,
        title="Old product",
    )
    new_snapshot = snapshot(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        total_active_quantity=7,
        title="Edited product",
    )
    ticket = ProductModeration(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        kind="CREATE",
        status="APPROVED",
        queue_priority=9,
        json_after=old_snapshot,
        decision_at=datetime.now(timezone.utc),
        date_moderation=datetime.now(timezone.utc),
        assigned_moderator_id=uuid4(),
        moderator_comment="approved before edit",
    )
    test_db.add(ticket)
    await test_db.commit()

    async def fake_get_product(self: B2BClient, requested_product_id: UUID) -> dict:
        assert requested_product_id == product_id
        return new_snapshot

    monkeypatch.setattr("src.services.b2b_client.B2BClient.get_product", fake_get_product)

    response = await async_client.post(
        "/api/v1/b2b/events",
        json={
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "category_id": str(category_id),
            },
        },
        headers=auth_headers(),
    )

    assert response.status_code == 202
    await test_db.refresh(ticket)
    assert ticket.status == "PENDING"
    assert ticket.kind == "EDIT"
    assert ticket.queue_priority == 3
    assert ticket.assigned_moderator_id is None
    assert ticket.decision_at is None
    assert ticket.date_moderation is None
    assert ticket.moderator_comment is None
    assert ticket.json_before == old_snapshot
    assert ticket.json_after == new_snapshot


async def test_edited_updates_in_review(async_client, test_db: AsyncSession, monkeypatch):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", SERVICE_KEY)
    product_id = uuid4()
    seller_id = uuid4()
    category_id = uuid4()
    moderator_id = uuid4()
    old_snapshot = snapshot(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        title="In review before edit",
    )
    new_snapshot = snapshot(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        title="In review after edit",
    )
    ticket = ProductModeration(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        kind="CREATE",
        status="IN_REVIEW",
        queue_priority=6,
        json_after=old_snapshot,
        assigned_moderator_id=moderator_id,
        claimed_at=datetime.now(timezone.utc),
        claim_expires_at=datetime.now(timezone.utc),
    )
    test_db.add(ticket)
    await test_db.flush()
    test_db.add(
        ModerationFieldReport(
            product_moderation_id=ticket.id,
            field_name="description",
            comment="old report",
        )
    )
    await test_db.commit()

    async def fake_get_product(self: B2BClient, requested_product_id: UUID) -> dict:
        assert requested_product_id == product_id
        return new_snapshot

    monkeypatch.setattr("src.services.b2b_client.B2BClient.get_product", fake_get_product)

    response = await async_client.post(
        "/api/v1/b2b/events",
        json={
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "category_id": str(category_id),
            },
        },
        headers=auth_headers(),
    )

    assert response.status_code == 202
    await test_db.refresh(ticket)
    assert ticket.status == "PENDING"
    assert ticket.kind == "EDIT"
    assert ticket.queue_priority == 6
    assert ticket.assigned_moderator_id is None
    assert ticket.claimed_at is None
    assert ticket.claim_expires_at is None
    assert ticket.json_before == old_snapshot
    assert ticket.json_after == new_snapshot

    report_count = await test_db.scalar(
        select(func.count(ModerationFieldReport.id)).where(
            ModerationFieldReport.product_moderation_id == ticket.id
        )
    )
    assert report_count == 0


async def test_deleted_archived(async_client, test_db: AsyncSession, monkeypatch):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", SERVICE_KEY)
    product_id = uuid4()
    seller_id = uuid4()
    category_id = uuid4()
    ticket = ProductModeration(
        product_id=product_id,
        seller_id=seller_id,
        category_id=category_id,
        status="PENDING",
        queue_priority=1,
        json_after=snapshot(product_id=product_id, seller_id=seller_id, category_id=category_id),
    )
    test_db.add(ticket)
    await test_db.flush()
    test_db.add(
        ModerationFieldReport(
            product_moderation_id=ticket.id,
            field_name="title",
            comment="to be deleted",
        )
    )
    await test_db.commit()

    response = await async_client.post(
        "/api/v1/events/product",
        json={
            "event": "DELETED",
            "idempotency_key": str(uuid4()),
            "product_id": str(product_id),
            "seller_id": str(seller_id),
            "date": datetime.now(timezone.utc).isoformat(),
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert await count_tickets(test_db, product_id) == 0
    report_count = await test_db.scalar(select(func.count(ModerationFieldReport.id)))
    assert report_count == 0


async def test_duplicate_event_no_side_effects(async_client, test_db: AsyncSession, monkeypatch):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", SERVICE_KEY)
    product_id = uuid4()
    seller_id = uuid4()
    category_id = uuid4()
    idempotency_key = str(uuid4())
    product_snapshot = snapshot(product_id=product_id, seller_id=seller_id, category_id=category_id)
    calls = 0

    async def fake_get_product(self: B2BClient, requested_product_id: UUID) -> dict:
        nonlocal calls
        calls += 1
        return product_snapshot

    monkeypatch.setattr("src.services.b2b_client.B2BClient.get_product", fake_get_product)

    payload = {
        "event_type": "PRODUCT_CREATED",
        "idempotency_key": idempotency_key,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "product_id": str(product_id),
            "seller_id": str(seller_id),
            "category_id": str(category_id),
        },
    }

    first_response = await async_client.post(
        "/api/v1/b2b/events",
        json=payload,
        headers=auth_headers(),
    )
    second_response = await async_client.post(
        "/api/v1/b2b/events",
        json=payload,
        headers=auth_headers(),
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert calls == 1
    assert await count_tickets(test_db, product_id) == 1


async def test_missing_service_header_401(async_client, monkeypatch):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", SERVICE_KEY)
    response = await async_client.post(
        "/api/v1/events/product",
        json={
            "event": "CREATED",
            "idempotency_key": str(uuid4()),
            "product_id": str(uuid4()),
            "seller_id": str(uuid4()),
            "date": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
