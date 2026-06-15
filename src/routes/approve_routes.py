from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dependencies import get_current_moderator_id, get_db
from src.schemas.approve import (
    ApproveTicketRequest,
    ModerationTicketResponse,
)
from src.schemas.error import ErrorResponse
from src.services.approve_service import ApproveService

router = APIRouter(tags=["Product moderation"])


@router.post(
    "/tickets/{ticket_id}/approve",
    response_model=ModerationTicketResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Ticket assigned to another moderator"},
        404: {"model": ErrorResponse, "description": "Product not found in moderation queue"},
        409: {"model": ErrorResponse, "description": "Wrong ticket status or product has no SKUs"},
        500: {"model": ErrorResponse, "description": "B2B event delivery failed"},
    },
)
async def approve_ticket(
    ticket_id: UUID,
    data: ApproveTicketRequest | None = None,
    moderator_id: UUID = Depends(get_current_moderator_id),
    db: AsyncSession = Depends(get_db),
) -> ModerationTicketResponse:
    service = ApproveService(db)
    return await service.approve_by_ticket_id(
        ticket_id=ticket_id,
        moderator_id=moderator_id,
        comment=data.comment if data is not None else None,
    )
