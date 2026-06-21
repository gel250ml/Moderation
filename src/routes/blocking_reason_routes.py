from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dependencies import get_db
from src.schemas.blocking_reason import (
    BlockingReasonAdminResponse,
    BlockingReasonCreateRequest,
    BlockingReasonResponse,
    BlockingReasonUpdateRequest,
)
from src.schemas.error import ErrorResponse
from src.services.blocking_reason_service import BlockingReasonService

router = APIRouter(tags=["BlockingReasons"])


@router.get(
    "/blocking-reasons",
    response_model=list[BlockingReasonResponse],
    responses={200: {"description": "Blocking reasons list"}},
)
async def list_blocking_reasons(
    hard_block: bool | None = Query(default=None, description="Filter by block type"),
    is_active: bool | None = Query(default=True, description="Filter by active state"),
    db: AsyncSession = Depends(get_db),
) -> list[BlockingReasonResponse]:
    service = BlockingReasonService(db)
    return await service.list_reasons(hard_block=hard_block, is_active=is_active)


@router.get(
    "/product-blocking-reasons",
    response_model=list[BlockingReasonResponse],
    include_in_schema=False,
)
async def list_product_blocking_reasons_alias(
    hard_block: bool | None = Query(default=None),
    is_active: bool | None = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> list[BlockingReasonResponse]:
    service = BlockingReasonService(db)
    return await service.list_reasons(hard_block=hard_block, is_active=is_active)


@router.get(
    "/admin/blocking-reasons",
    response_model=list[BlockingReasonAdminResponse],
    include_in_schema=False,
)
async def admin_list_blocking_reasons(
    hard_block: bool | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[BlockingReasonAdminResponse]:
    service = BlockingReasonService(db)
    return await service.list_reasons(hard_block=hard_block, is_active=is_active)


@router.post(
    "/blocking-reasons",
    status_code=status.HTTP_201_CREATED,
    response_model=BlockingReasonResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        409: {"model": ErrorResponse, "description": "Blocking reason code already exists"},
    },
)
@router.post(
    "/admin/blocking-reasons",
    status_code=status.HTTP_201_CREATED,
    response_model=BlockingReasonResponse,
    include_in_schema=False,
)
async def admin_create_blocking_reason(
    data: BlockingReasonCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> BlockingReasonResponse:
    service = BlockingReasonService(db)
    return await service.create_reason(data)


@router.patch(
    "/blocking-reasons/{reason_id}",
    response_model=BlockingReasonResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Blocking reason not found"},
        409: {"model": ErrorResponse, "description": "Blocking reason code already exists"},
    },
)
@router.patch(
    "/admin/blocking-reasons/{reason_id}",
    response_model=BlockingReasonResponse,
    include_in_schema=False,
)
async def admin_update_blocking_reason(
    reason_id: UUID,
    data: BlockingReasonUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> BlockingReasonResponse:
    service = BlockingReasonService(db)
    return await service.update_reason(reason_id, data)


@router.delete(
    "/blocking-reasons/{reason_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse, "description": "Blocking reason not found"}},
)
@router.delete(
    "/admin/blocking-reasons/{reason_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def admin_deactivate_blocking_reason(
    reason_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    service = BlockingReasonService(db)
    await service.deactivate_reason(reason_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
