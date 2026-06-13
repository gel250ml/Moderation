import base64
import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.blocking_reason import BlockingReason
from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration


HARD_REASON_ID = UUID("b8c9d0e1-2345-6789-f012-901234567890")


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


async def create_hard_reason(test_db: AsyncSession) -> BlockingReason:
    reason = BlockingReason(
        id=HARD_REASON_ID,
        title="Контрафактный товар",
        description="Жёсткая блокировка: контрафактный товар",
        hard_block=True,
    )
    test_db.add(reason)
    await test_db.commit()
    await test_db.refresh(reason)
    return reason


async def get_ticket(test_db: AsyncSession, ticket_id: UUID) -> ProductModeration | None:
    result = await test_db.execute(
        select(ProductModeration).where(ProductModeration.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is not None:
        await test_db.refresh(ticket)
    return ticket


async def count_tickets(test_db: AsyncSession, product_id: UUID) -> int:
    result = await test_db.execute(
        select(func.count(ProductModeration.id)).where(ProductModeration.product_id == product_id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_hard_block_transitions_to_terminal_and_emits_event(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    reason = await create_hard_reason(test_db)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/block",
            json={
                "blocking_reason_ids": [str(reason.id)],
                "comment": "Товар является контрафактом, подтверждено проверкой",
                "field_reports": [],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(ticket.id)
    assert body["product_id"] == str(ticket.product_id)
    assert body["status"] == "HARD_BLOCKED"

    updated = await get_ticket(test_db, ticket.id)
    assert updated is not None
    assert updated.status == "HARD_BLOCKED"
    assert updated.decision_at is not None
    assert updated.date_moderation is not None
    assert updated.blocking_reason_id == reason.id
    assert updated.moderator_comment == "Товар является контрафактом, подтверждено проверкой"

    mock_send.assert_awaited_once_with(
        product_id=ticket.product_id,
        ticket_idempotency_key=uuid5(NAMESPACE_URL, f"moderation:ticket:{ticket.id}:hard_blocked"),
        hard_block=True,
        blocking_reason_id=reason.id,
        blocking_reason_title="Контрафактный товар",
        moderator_comment="Товар является контрафактом, подтверждено проверкой",
        field_reports=[],
    )


@pytest.mark.asyncio
async def test_hard_block_event_carries_hard_block_true(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    reason = await create_hard_reason(test_db)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(reason.id),
                "moderator_comment": "Контрафакт",
                "field_reports": [
                    {
                        "field_path": "images[0].url",
                        "message": "Изображение подтверждает нарушение",
                        "severity": "ERROR",
                    }
                ],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 200
    assert response.json() == {"product_id": str(ticket.product_id), "status": "HARD_BLOCKED"}

    kwargs = mock_send.await_args.kwargs
    assert kwargs["hard_block"] is True
    assert kwargs["blocking_reason_id"] == reason.id
    assert kwargs["blocking_reason_title"] == "Контрафактный товар"
    assert kwargs["field_reports"] == [
        {
            "field_name": "images[0].url",
            "sku_id": None,
            "comment": "Изображение подтверждает нарушение",
        }
    ]


@pytest.mark.asyncio
async def test_any_modify_on_hard_blocked_returns_403(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id, status="HARD_BLOCKED")
    reason = await create_hard_reason(test_db)

    with patch(
        "src.services.b2b_client.B2BClient.ensure_product_has_skus",
        new_callable=AsyncMock,
    ) as mock_has_skus, patch(
        "src.services.b2b_client.B2BClient.send_moderated_event",
        new_callable=AsyncMock,
    ) as mock_moderated:
        approve_response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/approve",
            json={"comment": "ok"},
            headers=auth_headers(moderator_id),
        )

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_blocked:
        block_response = await async_client.post(
            f"/api/v1/tickets/{ticket.id}/block",
            json={
                "blocking_reason_ids": [str(reason.id)],
                "comment": "another decision",
                "field_reports": [],
            },
            headers=auth_headers(moderator_id),
        )

    assert approve_response.status_code == 403
    assert approve_response.json()["code"] == "FORBIDDEN"
    assert block_response.status_code == 403
    assert block_response.json()["code"] == "FORBIDDEN"
    updated = await get_ticket(test_db, ticket.id)
    assert updated is not None
    assert updated.status == "HARD_BLOCKED"
    mock_has_skus.assert_not_awaited()
    mock_moderated.assert_not_awaited()
    mock_blocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_edited_event_on_hard_blocked_is_ignored(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", "b2b-test-key")
    ticket = await create_ticket(test_db, moderator_id=uuid4(), status="HARD_BLOCKED")

    response = await async_client.post(
        "/api/v1/b2b/events",
        json={
            "idempotency_key": str(uuid4()),
            "product_id": str(ticket.product_id),
            "seller_id": str(ticket.seller_id),
            "event": "EDITED",
        },
        headers={"X-Service-Key": "b2b-test-key"},
    )

    assert response.status_code == 200
    updated = await get_ticket(test_db, ticket.id)
    assert updated is not None
    assert updated.status == "HARD_BLOCKED"
    assert updated.assigned_moderator_id == ticket.assigned_moderator_id


@pytest.mark.asyncio
async def test_deleted_event_removes_hard_blocked(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("src.database.dependencies.B2B_TO_MOD_KEY", "b2b-test-key")
    ticket = await create_ticket(test_db, moderator_id=uuid4(), status="HARD_BLOCKED")
    test_db.add(
        ModerationFieldReport(
            id=uuid4(),
            product_moderation_id=ticket.id,
            field_name="description",
            sku_id=None,
            comment="old report",
        )
    )
    await test_db.commit()

    response = await async_client.post(
        "/api/v1/b2b/events",
        json={
            "event_type": "PRODUCT_DELETED",
            "payload": {"product_id": str(ticket.product_id)},
        },
        headers={"X-Service-Key": "b2b-test-key"},
    )

    assert response.status_code == 200
    assert await count_tickets(test_db, ticket.product_id) == 0
