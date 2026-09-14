import pytest

from app.db.session import AsyncSessionLocal
from app.models.enums import OperatorRole, PublicationErrorCode, PublicationJobStatus
from app.services.operator_auth import create_operator_user
from app.services.publication import create_publication_intent, process_publication_job
from tests.test_publication_control import seed_approved_listing

pytestmark = pytest.mark.usefixtures("clean_database")


async def login(client, username: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    token = response.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": token})
    return token


async def test_control_api_requires_authentication(unauthenticated_client):
    response = await unauthenticated_client.get("/api/v1/control/overview")
    assert response.status_code == 401


async def test_login_session_current_user_and_logout_csrf(client):
    current = await client.get("/api/v1/auth/session")
    assert current.status_code == 200
    assert current.json()["username"] == "admin"

    missing_csrf = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": ""})
    assert missing_csrf.status_code == 403

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    after = await client.get("/api/v1/auth/session")
    assert after.status_code == 401


async def test_role_authorization_viewer_read_only(unauthenticated_client):
    async with AsyncSessionLocal() as session:
        await create_operator_user(session, "viewer", "viewer-password", OperatorRole.VIEWER)
    await login(unauthenticated_client, "viewer", "viewer-password")

    read = await unauthenticated_client.get("/api/v1/control/overview")
    assert read.status_code == 200

    mutate = await unauthenticated_client.post("/api/v1/control/recalculate")
    assert mutate.status_code == 403


async def test_login_rate_limit(unauthenticated_client):
    async with AsyncSessionLocal() as session:
        await create_operator_user(session, "limited", "right-password", OperatorRole.OPERATOR)
    for _ in range(5):
        response = await unauthenticated_client.post("/api/v1/auth/login", json={"username": "limited", "password": "wrong"})
        assert response.status_code == 401
    blocked = await unauthenticated_client.post("/api/v1/auth/login", json={"username": "limited", "password": "wrong"})
    assert blocked.status_code == 429


async def test_dashboard_variant_detail_alerts_audit_settings_and_health(client):
    variant_id, _listing_id = await seed_approved_listing()
    dashboard = await client.get("/api/v1/operator/dashboard")
    products = await client.get("/api/v1/operator/products")
    detail = await client.get(f"/api/v1/operator/products/{variant_id}")
    alerts = await client.get("/api/v1/operator/alerts")
    audit = await client.get("/api/v1/operator/audit")
    settings = await client.get("/api/v1/operator/settings")
    health = await client.get("/api/v1/operator/system/health")

    assert dashboard.status_code == 200
    assert dashboard.json()["counts"]["products"] >= 1
    assert products.status_code == 200
    assert products.json()["total"] >= 1
    assert detail.status_code == 200
    assert detail.json()["identity"]["variant_id"] == str(variant_id)
    assert alerts.status_code == audit.status_code == settings.status_code == health.status_code == 200
    assert settings.json()["avito_live_enabled"] is False
    assert health.json()["avito_real_mutation"] == "DISABLED_CONTRACT_INCOMPLETE"


async def test_publication_job_detail_and_avito_guard_retained(client):
    _variant_id, listing_id = await seed_approved_listing()
    async with AsyncSessionLocal() as session:
        _intent, job, _created = await create_publication_intent(session, listing_id, requested_by="qa", dry_run=False)
        blocked = await process_publication_job(session, job.id, execute_real=True)

    detail = await client.get(f"/api/v1/operator/publication/jobs/{blocked.id}")
    assert detail.status_code == 200
    assert detail.json()["job"]["status"] == PublicationJobStatus.BLOCKED.value
    assert detail.json()["job"]["error_code"] == PublicationErrorCode.AVITO_CONTRACT_INCOMPLETE.value
    assert detail.json()["avito_real_mutation"] == "DISABLED_CONTRACT_INCOMPLETE"


async def test_backup_smoke_requires_admin_and_creates_manifest(client):
    response = await client.post("/api/v1/operator/backups/smoke")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["size_bytes"] > 0
