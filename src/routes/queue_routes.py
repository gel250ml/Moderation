from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dependencies import get_current_moderator_id, get_db
from src.schemas.error import ErrorResponse
from src.schemas.queue import GetNextQueueRequest, GetNextQueueResponse
from src.services.queue_service import QueueService

router = APIRouter(tags=["Product moderation"])


@router.post(
    "/product-moderation/get-next",
    response_model=GetNextQueueResponse,
    status_code=status.HTTP_200_OK,
    responses={
        204: {"description": "Queue is empty"},
        400: {"model": ErrorResponse, "description": "Invalid queueId"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        409: {"model": ErrorResponse, "description": "Moderator already has active IN_REVIEW card"},
    },
)
async def get_next_product_moderation_card(
    data: GetNextQueueRequest | None = None,
    moderator_id: UUID = Depends(get_current_moderator_id),
    db: AsyncSession = Depends(get_db),
) -> GetNextQueueResponse | Response:
    service = QueueService(db)
    ticket = await service.get_next_card(
        moderator_id=moderator_id,
        queue_id=data.queue_id if data is not None else None,
    )
    if ticket is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return GetNextQueueResponse.from_ticket(ticket)
