from src.database.session import engine
from src.database.base import Base

# ВАЖНО: импортируем модели, чтобы они зарегистрировались в metadata
from src.models import *


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)