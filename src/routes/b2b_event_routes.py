from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dependencies import get_db, verify_b2b_service_key
from src.schemas.b2b_event import B2BEventRequest, B2BEventResponse
from src.schemas.error import ErrorResponse
from src.services.b2b_event_service import B2BEventService

router = APIRouter(tags=["B2B Events"])


async def _apply_product_event(data: B2BEventRequest, db: AsyncSession) -> B2BEventResponse:
    service = B2BEventService(db)
    await service.apply(data)
    return B2BEventResponse()


@router.post(
    "/b2b/events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=B2BEventResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Invalid service key"},
    },
)
async def apply_b2b_event(
    data: B2BEventRequest,
    _: None = Depends(verify_b2b_service_key),
    db: AsyncSession = Depends(get_db),
) -> B2BEventResponse:
    return await _apply_product_event(data, db)


@router.post(
    "/events/product",
    status_code=status.HTTP_200_OK,
    response_model=B2BEventResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Invalid service key"},
    },
)
async def apply_legacy_product_event(
    data: B2BEventRequest,
    _: None = Depends(verify_b2b_service_key),
    db: AsyncSession = Depends(get_db),
) -> B2BEventResponse:
    return await _apply_product_event(data, db)
