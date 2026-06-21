import base64
import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.blocking_reason import BlockingReason
from src.models.moderation_field_report import ModerationFieldReport
from src.models.product_moderation import ProductModeration


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


async def create_reason(
    test_db: AsyncSession,
    *,
    hard_block: bool = False,
) -> BlockingReason:
    reason = BlockingReason(
        id=uuid4(),
        code="HARD_REASON" if hard_block else "SOFT_REASON",
        title="Reason",
        description="Reason description",
        hard_block=hard_block,
        is_active=True,
    )
    test_db.add(reason)
    await test_db.commit()
    await test_db.refresh(reason)
    return reason


async def get_ticket(test_db: AsyncSession, ticket_id: UUID) -> ProductModeration:
    result = await test_db.execute(
        select(ProductModeration).where(ProductModeration.id == ticket_id)
    )
    ticket = result.scalar_one()
    await test_db.refresh(ticket)
    return ticket


async def get_field_reports(test_db: AsyncSession, ticket_id: UUID) -> list[ModerationFieldReport]:
    result = await test_db.execute(
        select(ModerationFieldReport)
        .where(ModerationFieldReport.product_moderation_id == ticket_id)
        .order_by(ModerationFieldReport.field_name)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_soft_block_transitions_to_blocked_with_field_reports(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    sku_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    reason = await create_reason(test_db)
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

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ):
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(reason.id),
                "moderator_comment": "Fix the product details and images",
                "field_reports": [
                    {
                        "field_name": "title",
                        "comment": "Title does not match the product",
                    },
                    {
                        "field_name": "sku_price",
                        "sku_id": str(sku_id),
                        "comment": "Price is suspicious",
                    },
                ],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 200
    assert response.json() == {"product_id": str(ticket.product_id), "status": "BLOCKED"}

    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "BLOCKED"
    assert updated.decision_at is not None
    assert updated.date_moderation is not None
    assert updated.blocking_reason_id == reason.id
    assert updated.moderator_comment == "Fix the product details and images"

    reports = await get_field_reports(test_db, ticket.id)
    assert [(report.field_name, report.sku_id, report.comment) for report in reports] == [
        ("sku_price", sku_id, "Price is suspicious"),
        ("title", None, "Title does not match the product"),
    ]


@pytest.mark.asyncio
async def test_soft_block_emits_event_to_b2b(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    reason = await create_reason(test_db)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(reason.id),
                "moderator_comment": "Please fix the description",
                "field_reports": [
                    {
                        "field_name": "description",
                        "comment": "Description is incomplete",
                    }
                ],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 200
    mock_send.assert_awaited_once_with(
        product_id=ticket.product_id,
        ticket_idempotency_key=uuid5(NAMESPACE_URL, f"moderation:ticket:{ticket.id}:blocked"),
        hard_block=False,
        blocking_reason_id=reason.id,
        blocking_reason_title="Reason",
        moderator_comment="Please fix the description",
        field_reports=[
            {
                "field_name": "description",
                "sku_id": None,
                "comment": "Description is incomplete",
            }
        ],
    )


@pytest.mark.asyncio
async def test_soft_block_unknown_reason_returns_400(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(uuid4()),
                "moderator_comment": "Unknown reason",
                "field_reports": [],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "IN_REVIEW"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_block_others_card_returns_403(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    assigned_moderator_id = uuid4()
    current_moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=assigned_moderator_id)
    reason = await create_reason(test_db)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(reason.id),
                "moderator_comment": "Someone else owns this card",
                "field_reports": [],
            },
            headers=auth_headers(current_moderator_id),
        )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "IN_REVIEW"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_block_invalid_field_name_returns_400(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    reason = await create_reason(test_db)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(reason.id),
                "moderator_comment": "Invalid field name",
                "field_reports": [
                    {
                        "field_name": "barcode",
                        "comment": "Unsupported field",
                    }
                ],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "IN_REVIEW"
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_block_hard_only_reason_returns_400(
    test_db: AsyncSession,
    async_client: httpx.AsyncClient,
):
    moderator_id = uuid4()
    ticket = await create_ticket(test_db, moderator_id=moderator_id)
    reason = await create_reason(test_db, hard_block=True)

    with patch(
        "src.services.b2b_client.B2BClient.send_blocked_event",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await async_client.post(
            f"/api/v1/products/{ticket.product_id}/decline",
            json={
                "blocking_reason_id": str(reason.id),
                "moderator_comment": "Hard reason cannot soft block",
                "field_reports": [],
            },
            headers=auth_headers(moderator_id),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert response.json()["message"] == "Hard-only blocking reason cannot be used for soft block"
    updated = await get_ticket(test_db, ticket.id)
    assert updated.status == "IN_REVIEW"
    mock_send.assert_not_awaited()
