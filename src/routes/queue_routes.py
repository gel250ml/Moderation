from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dependencies import get_current_moderator_id, get_db
from src.schemas.error import ErrorResponse
from src.schemas.queue import QueueClaimRequest, TicketResponse
from src.services.queue_service import QueueService

router = APIRouter(tags=["Queue"])


@router.post(
    "/queue/claim",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    responses={
        204: {"description": "Queue is empty"},
        400: {"model": ErrorResponse, "description": "Invalid queue_priority"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        409: {"model": ErrorResponse, "description": "Moderator already has active IN_REVIEW card"},
    },
)
async def claim_queue_ticket(
    data: QueueClaimRequest | None = None,
    moderator_id: UUID = Depends(get_current_moderator_id),
    db: AsyncSession = Depends(get_db),
) -> TicketResponse | Response:
    service = QueueService(db)
    ticket = await service.get_next_card(
        moderator_id=moderator_id,
        queue_priority=data.queue_priority if data is not None else None,
    )
    if ticket is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return TicketResponse.from_ticket(ticket)
