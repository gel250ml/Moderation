import base64
import json
from typing import AsyncGenerator
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database.base import Base
from src.database.dependencies import get_db
from src.main import app


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestingSession = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with TestingSession() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def seller_id() -> UUID:
    return uuid4()


@pytest.fixture
def other_seller_id() -> UUID:
    return uuid4()


def create_jwt_token(seller_id: UUID) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"seller_id": str(seller_id), "sub": str(seller_id)}

    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"signature").decode().rstrip("=")

    return f"{header_b64}.{payload_b64}.{signature}"


@pytest_asyncio.fixture
async def async_client(test_db: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()
