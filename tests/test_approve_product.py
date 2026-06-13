import base64
import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration
from src.services.b2b_client import B2BProductUnavailableError


def create_moderator_jwt(moderator_id: UUID) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"moderator_id": str(moderator_id), "sub": str(moderator_id)}

    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"signature").decode().rstrip("=")

    return f"{header_b64}.{payload_b64}.{signature}"


def auth_headers(moderator_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_moderator_jwt(moderator_id)}"}


async def create_ticket(
    test_db: AsyncSession,
    *,
    moderator_id: UUID | None,
    status: str = "IN_REVIEW",
) -> ProductModeration:
    ticket = ProductModeration(
        id=uuid4(),
        product_id=uuid4(),
        seller_id=uuid4(),
        category_id=uuid4(),
        kind="CREATE",
        status=status,
        queue_priority=4,
        assigned_moderator_id=moderator_id,
    )
    test_db.add(ticket)
    await test_db.commit()
    await test_db.refresh(ticket)
    return ticket


async def get_ticket(test_db: AsyncSession, ticket_id: UUID) -> ProductModeration:
    result = await test_db.execute(
        select(ProductModeration).where(ProductModeration.id == ticket_id)
    )
    ticket = result.scalar_one()
    await test_db.refresh(ticket)
    return ticket


async def count_field_reports(test_db: AsyncSession, ticket_id: UUID) -> int:
    result = await test_db.execute(
        select(func.count(ModerationFieldReport.id)).where(
            ModerationFieldReport.product_moderation_id == ticket_id
        )
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_approve_transitions_to_moderated_and_emits_event(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    test_db.add(
        ModerationFieldReport(
            id=uuid4(),
            product_moderation_id=ticket.id,
            field_name="description",
            sku_id=None,
            comment="Old report",
        )
    )
    await test_db.commit()

    with patch(
        "src.services.b2b_client.B2BClient.ensure_product_has_skus",
        new_callable=AsyncMock,
    ) as mock_has_skus, patch(
        "src.services.b2b_client.B2BClient.send_moderated_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/approve",
            json={"comment": "Товар соответствует требованиям"},
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(ticket.id)
    assert body["product_id"] == str(ticket.product_id)
    assert body["status"] == "MODERATED"

    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "MODERATED"
    assert updated.decision_at is not None
    assert updated.date_moderation is not None
    assert updated.moderator_comment == "Товар соответствует требованиям"
    assert updated.blocking_reason_id is None
    assert await count_field_reports(test_db, ticket.id) == 0

    mock_has_skus.assert_awaited_once_with(ticket.product_id)
    mock_send.assert_awaited_once_with(
        product_id=ticket.product_id,
        ticket_idempotency_key=uuid5(NAMESPACE_URL, f"moderation:ticket:{ticket.id}:moderated"),
        moderator_id=moderator_id,
        moderator_comment="Товар соответствует требованиям",
    )


@pytest.mark.asyncio
async def test_approve_others_card_returns_403(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    assigned_moderator_id = uuid4()
    current_moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=assigned_moderator_id)

    with patch(
        "src.services.b2b_client.B2BClient.ensure_product_has_skus",
        new_callable=AsyncMock,
    ) as mock_has_skus, patch(
        "src.services.b2b_client.B2BClient.send_moderated_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/approve",
            json={"comment": "ok"},
            headers=auth_headers(current_moderator_id),
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "IN_REVIEW"
    mock_has_skus.assert_not_awaited()
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_after_edited_returns_409(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id, status="EDITED")

    with patch(
        "src.services.b2b_client.B2BClient.ensure_product_has_skus",
        new_callable=AsyncMock,
    ) as mock_has_skus, patch(
        "src.services.b2b_client.B2BClient.send_moderated_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/approve",
            json={"comment": "ok"},
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "EDITED"
    mock_has_skus.assert_not_awaited()
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_without_sku_returns_409(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)

    with patch(
        "src.services.b2b_client.B2BClient.ensure_product_has_skus",
        new_callable=AsyncMock,
        side_effect=B2BProductUnavailableError("Product has no SKUs, cannot approve"),
    ) as mock_has_skus, patch(
        "src.services.b2b_client.B2BClient.send_moderated_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/approve",
            json={"comment": "ok"},
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "IN_REVIEW"
    mock_has_skus.assert_awaited_once_with(ticket.product_id)
    mock_send.assert_not_awaited()
