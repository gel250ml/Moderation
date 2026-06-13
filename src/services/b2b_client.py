import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx

from src.core.config import B2B_URL, MOD_TO_B2B_KEY

logger = logging.getLogger(__name__)


class B2BClientError(Exception):
    pass


class B2BProductNotFoundError(B2BClientError):
    pass


class B2BProductUnavailableError(B2BClientError):
    pass


class B2BClient:
    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or B2B_URL or "").rstrip("/")
        self.service_key = service_key or MOD_TO_B2B_KEY

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.service_key:
            headers["X-Service-Key"] = self.service_key
        return headers

    def _ensure_configured(self) -> None:
        if not self.base_url:
            raise B2BClientError("B2B_URL is not configured")
        if not self.service_key:
            raise B2BClientError("MOD_TO_B2B_KEY is not configured")

    async def get_product(self, product_id: UUID) -> dict:
        self._ensure_configured()
        url = f"{self.base_url}/api/v1/products/{product_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            logger.exception("Failed to fetch product %s from B2B", product_id)
            raise B2BClientError("B2B product request failed") from exc

        if response.status_code == 404:
            raise B2BProductNotFoundError("Product not found in B2B")
        if response.status_code not in (200,):
            raise B2BClientError("B2B product request failed")

        return response.json()

    async def ensure_product_has_skus(self, product_id: UUID) -> None:
        product = await self.get_product(product_id)
        skus = product.get("skus") or []
        if not skus:
            raise B2BProductUnavailableError("Product has no SKUs, cannot approve")

    async def send_moderated_event(
        self,
        *,
        product_id: UUID,
        ticket_idempotency_key: UUID,
        moderator_id: UUID,
        moderator_comment: str | None,
    ) -> None:
        self._ensure_configured()
        url = f"{self.base_url}/api/v1/moderation/events"
        payload = {
            "idempotency_key": str(ticket_idempotency_key),
            "product_id": str(product_id),
            "event_type": "MODERATED",
            "moderator_id": str(moderator_id),
            "moderator_comment": moderator_comment,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            logger.exception("Failed to send MODERATED event for product %s to B2B", product_id)
            raise B2BClientError("B2B moderation event request failed") from exc

        if response.status_code not in (200, 202, 204):
            logger.error(
                "B2B rejected MODERATED event for product %s: status=%s body=%s",
                product_id,
                response.status_code,
                response.text,
            )
            raise B2BClientError("B2B rejected moderation event")


    async def send_blocked_event(
        self,
        *,
        product_id: UUID,
        ticket_idempotency_key: UUID,
        hard_block: bool,
        blocking_reason_id: UUID,
        blocking_reason_title: str,
        moderator_comment: str | None,
        field_reports: list[dict],
    ) -> None:
        self._ensure_configured()
        url = f"{self.base_url}/api/v1/events/moderation"
        payload = {
            "idempotency_key": str(ticket_idempotency_key),
            "product_id": str(product_id),
            "status": "BLOCKED",
            "hard_block": hard_block,
            "blocking_reason": {
                "id": str(blocking_reason_id),
                "title": blocking_reason_title,
                "comment": moderator_comment,
            },
            "field_reports": field_reports,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            logger.exception("Failed to send BLOCKED event for product %s to B2B", product_id)
            raise B2BClientError("B2B moderation event request failed") from exc

        if response.status_code not in (200, 202, 204):
            logger.error(
                "B2B rejected BLOCKED event for product %s: status=%s body=%s",
                product_id,
                response.status_code,
                response.text,
            )
            raise B2BClientError("B2B rejected moderation event")
