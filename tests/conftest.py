import os

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://avito:change_me_local_only@localhost:5432/avito_automation"),
)

from app.db.base import Base
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.enums import OperatorRole
from app.services.operator_auth import create_operator_user


@pytest.fixture(scope="session")
def apply_migrations() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")


@pytest.fixture
async def clean_database(apply_migrations) -> None:
    async with AsyncSessionLocal() as session:
        table_names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
        await session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest.fixture
async def client(clean_database) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        async with AsyncSessionLocal() as session:
            await create_operator_user(session, "admin", "correct horse battery staple", OperatorRole.ADMIN)
        login = await test_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "correct horse battery staple"},
        )
        assert login.status_code == 200
        test_client.headers.update({"X-CSRF-Token": login.json()["csrf_token"]})
        yield test_client


@pytest.fixture
async def unauthenticated_client(clean_database) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
