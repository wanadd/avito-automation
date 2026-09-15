import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.supplier import Supplier

pytestmark = pytest.mark.usefixtures("clean_database")


async def supplier_count() -> int:
    async with AsyncSessionLocal() as session:
        return int(await session.scalar(select(func.count()).select_from(Supplier)) or 0)


async def test_operator_can_create_first_supplier_when_zero_suppliers(client):
    assert await supplier_count() == 0
    response = await client.post("/api/v1/operator/suppliers", json={"name": " Hello Mobile A41-A42 ", "is_active": True})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Hello Mobile A41-A42"
    assert body["code"] == "hello-mobile-a41-a42"
    assert body["is_active"] is True
    assert await supplier_count() == 1
    async with AsyncSessionLocal() as session:
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "SUPPLIER_CREATED"))
    assert audit is not None


async def test_operator_supplier_create_rejects_blank_name(client):
    response = await client.post("/api/v1/operator/suppliers", json={"name": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "SUPPLIER_NAME_REQUIRED"
    assert await supplier_count() == 0


async def test_operator_supplier_duplicate_name_conflicts_without_duplicate_row(client):
    first = await client.post("/api/v1/operator/suppliers", json={"name": "Hello Mobile"})
    second = await client.post("/api/v1/operator/suppliers", json={"name": " hello mobile "})
    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert second.json()["detail"] == "SUPPLIER_NAME_EXISTS"
    assert await supplier_count() == 1


async def test_operator_supplier_create_requires_auth(unauthenticated_client):
    response = await unauthenticated_client.post("/api/v1/operator/suppliers", json={"name": "Hello Mobile"})
    assert response.status_code == 401
