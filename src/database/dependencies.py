import base64
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Header, HTTPException

from src.core.config import B2B_TO_MOD_KEY, MOD_TO_B2B_KEY
from src.database.session import async_session_maker


@dataclass(frozen=True)
class ProductAccessContext:
    mode: Literal["seller", "service"]
    seller_id: UUID | None = None


async def get_db():
    async with async_session_maker() as session:
        yield session


def _decode_jwt_payload(token: str) -> dict:
    try:
        _, payload, _ = token.split('.')
        payload += '=' * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload.encode())
        return json.loads(raw)
    except (ValueError, IndexError, json.JSONDecodeError):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid authorization token"},
        )


def _seller_id_from_authorization(authorization: str | None) -> UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Authorization token must be Bearer"},
        )

    payload = _decode_jwt_payload(authorization.split(" ", 1)[1])
    seller_id = payload.get("seller_id") or payload.get("sub")
    if seller_id is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "seller_id is missing from JWT claims"},
        )

    try:
        return UUID(str(seller_id))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "seller_id claim must be UUID"},
        )


async def get_current_seller_id(
    authorization: str = Header(..., alias="Authorization"),
) -> UUID:
    return _seller_id_from_authorization(authorization)


async def get_product_access_context(
    authorization: str | None = Header(None, alias="Authorization"),
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
) -> ProductAccessContext:
    if x_service_key is not None:
        if not B2B_TO_MOD_KEY or x_service_key != B2B_TO_MOD_KEY:
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "Invalid service key"},
            )
        return ProductAccessContext(mode="service")

    return ProductAccessContext(
        mode="seller",
        seller_id=_seller_id_from_authorization(authorization),
    )

async def verify_moderation_service_key(
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
) -> None:
    expected_key = MOD_TO_B2B_KEY or B2B_TO_MOD_KEY
    if not expected_key or x_service_key != expected_key:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid service key"},
        )
