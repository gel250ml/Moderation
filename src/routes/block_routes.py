from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dependencies import get_current_moderator_id, get_db
from src.schemas.block import (
    BlockTicketRequest,
    DeclineProductRequest,
    DeclineProductResponse,
    ModerationTicketBlockResponse,
)
from src.schemas.error import ErrorResponse
from src.services.block_service import BlockService

router = APIRouter(tags=["Product moderation"])


@router.post(
    "/tickets/{ticket_id}/block",
    response_model=ModerationTicketBlockResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Ticket assigned to another moderator or terminal status"},
        404: {"model": ErrorResponse, "description": "Product not found in moderation queue"},
        409: {"model": ErrorResponse, "description": "Wrong ticket status"},
        500: {"model": ErrorResponse, "description": "B2B event delivery failed"},
    },
)
async def block_ticket(
    ticket_id: UUID,
    data: BlockTicketRequest,
    moderator_id: UUID = Depends(get_current_moderator_id),
    db: AsyncSession = Depends(get_db),
) -> ModerationTicketBlockResponse:
    service = BlockService(db)
    return await service.block_by_ticket_id(
        ticket_id=ticket_id,
        moderator_id=moderator_id,
        blocking_reason_ids=data.blocking_reason_ids,
        comment=data.comment,
        field_reports=data.field_reports,
    )


@router.post(
    "/products/{product_id}/decline",
    response_model=DeclineProductResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Card assigned to another moderator or terminal status"},
        404: {"model": ErrorResponse, "description": "Product not found in moderation queue"},
        409: {"model": ErrorResponse, "description": "Wrong card status"},
        500: {"model": ErrorResponse, "description": "B2B event delivery failed"},
    },
)
async def decline_product(
    product_id: UUID,
    data: DeclineProductRequest,
    moderator_id: UUID = Depends(get_current_moderator_id),
    db: AsyncSession = Depends(get_db),
) -> DeclineProductResponse:
    service = BlockService(db)
    return await service.decline_by_product_id(
        product_id=product_id,
        moderator_id=moderator_id,
        blocking_reason_id=data.blocking_reason_id,
        moderator_comment=data.moderator_comment,
        field_reports=data.field_reports,
    )
