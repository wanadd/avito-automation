import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.prod.yml"
BOOTSTRAP_NGINX = ROOT / "deploy" / "nginx" / "avito.planam.ru.bootstrap.conf"
FINAL_NGINX = ROOT / "deploy" / "nginx" / "avito.planam.ru.conf.template"
ENV_EXAMPLE = ROOT / ".env.production.example"


def compose_config(*extra_args: str) -> dict:
    env = {
        **os.environ,
        "DOMAIN": "avito.planam.ru",
        "APP_BASE_URL": "https://avito.planam.ru",
        "POSTGRES_PASSWORD": "x" * 40,
        "SESSION_SECRET": "y" * 40,
        "ALLOWED_HOSTS": "avito.planam.ru,127.0.0.1,localhost,api,avito-automation-api",
        "CORS_ORIGINS": "https://avito.planam.ru",
        "COMPOSE_PROJECT_NAME": "avito_automation_prod",
    }
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), *extra_args, "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def service_ports(config: dict, service: str) -> list[dict]:
    return config["services"].get(service, {}).get("ports", []) or []


def service_networks(config: dict, service: str) -> dict:
    return config["services"].get(service, {}).get("networks", {}) or {}


def test_shared_prod_compose_does_not_start_avito_nginx_by_default():
    config = compose_config()
    assert "nginx" not in config["services"]
    assert service_ports(config, "api") == []
    assert service_ports(config, "web") == []

    standalone = compose_config("--profile", "standalone-ingress")
    assert standalone["services"]["nginx"].get("profiles") == ["standalone-ingress"]


def test_shared_prod_compose_does_not_expose_postgres_or_redis():
    config = compose_config()
    assert service_ports(config, "postgres") == []
    assert service_ports(config, "redis") == []
    assert "planam_ingress" not in service_networks(config, "postgres")
    assert "planam_ingress" not in service_networks(config, "redis")


def test_shared_prod_compose_uses_unique_planam_ingress_aliases():
    config = compose_config()
    web_ingress = service_networks(config, "web")["planam_ingress"]
    api_ingress = service_networks(config, "api")["planam_ingress"]
    assert web_ingress["aliases"] == ["avito-automation-web"]
    assert api_ingress["aliases"] == ["avito-automation-api"]
    assert "planam_ingress" not in service_networks(config, "worker")
    assert "planam_ingress" not in service_networks(config, "scheduler")


def test_shared_prod_compose_web_binds_all_interfaces_and_uses_health_route():
    config = compose_config()
    web = config["services"]["web"]
    assert web["environment"]["HOSTNAME"] == "0.0.0.0"
    assert web["environment"]["PORT"] == "3000"
    assert web["environment"]["API_BASE_URL"] == "http://api:8000"
    assert "NEXT_PUBLIC_API_BASE_URL" not in web["environment"]
    assert "http://127.0.0.1:3000/health" in web["healthcheck"]["test"][-1]
    assert "operator/dashboard" not in web["healthcheck"]["test"][-1]


def test_bootstrap_nginx_does_not_reference_tls_certificate():
    text = BOOTSTRAP_NGINX.read_text(encoding="utf-8")
    assert "listen 80" in text
    assert "avito.planam.ru" in text
    assert "ssl_certificate" not in text
    assert "/etc/letsencrypt" not in text


def test_final_nginx_uses_correct_domain_certs_and_dynamic_aliases():
    text = FINAL_NGINX.read_text(encoding="utf-8")
    assert "server_name avito.planam.ru" in text
    assert "/etc/letsencrypt/live/avito.planam.ru/fullchain.pem" in text
    assert "/etc/letsencrypt/live/avito.planam.ru/privkey.pem" in text
    assert "resolver 127.0.0.11 valid=10s ipv6=off" in text
    assert "set $avito_api http://avito-automation-api:8000;" in text
    assert "set $avito_web http://avito-automation-web:3000;" in text
    assert "proxy_pass $avito_api;" in text
    assert "proxy_pass $avito_web;" in text
    assert "upstream " not in text


def test_env_example_contains_no_real_secrets_and_uses_target_domain():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "DOMAIN=avito.planam.ru" in text
    assert "APP_BASE_URL=https://avito.planam.ru" in text
    assert "NEXT_PUBLIC_API_BASE_URL" not in text
    assert "ALLOWED_HOSTS=avito.planam.ru,127.0.0.1,localhost,api,avito-automation-api" in text
    assert "ALLOWED_HOSTS=*" not in text
    assert "COMPOSE_PROJECT_NAME=avito_automation_prod" in text
    assert "password123" not in text.lower()
    assert "changeme" not in text.lower()
    assert "TELEGRAM_API_HASH=" in text
    assert "AVITO_CLIENT_SECRET" not in text
    assert "AVITO_TOKEN" not in text


def test_shared_ingress_patch_does_not_enable_live_avito_integration():
    compose_text = COMPOSE.read_text(encoding="utf-8")
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    nginx_text = FINAL_NGINX.read_text(encoding="utf-8")
    combined = "\n".join([compose_text, env_text, nginx_text])
    assert "AVITO_CLIENT_ID" not in combined
    assert "AVITO_CLIENT_SECRET" not in combined
    assert "AVITO_ACCESS_TOKEN" not in combined


def test_prod_env_validator_accepts_safe_env_and_rejects_placeholders(tmp_path):
    safe_password = "p" * 40
    safe_secret = "s" * 40
    safe_env = tmp_path / "safe.env"
    safe_env.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "DOMAIN=avito.planam.ru",
                "APP_BASE_URL=https://avito.planam.ru",
                "POSTGRES_DB=avito_automation",
                "POSTGRES_USER=avito",
                f"POSTGRES_PASSWORD={safe_password}",
                f"DATABASE_URL=postgresql+asyncpg://avito:{safe_password}@postgres:5432/avito_automation",
                "REDIS_URL=redis://redis:6379/0",
                f"SESSION_SECRET={safe_secret}",
                "COOKIE_SECURE=true",
                "ALLOWED_HOSTS=avito.planam.ru,127.0.0.1,localhost,api,avito-automation-api",
                "CORS_ORIGINS=https://avito.planam.ru",
                "COMPOSE_PROJECT_NAME=avito_automation_prod",
            ]
        ),
        encoding="utf-8",
    )
    safe = subprocess.run(
        ["python", "scripts/validate_prod_env.py", str(safe_env)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert safe.returncode == 0
    assert "PROD ENV VALIDATION: PASS" in safe.stdout
    assert safe_password not in safe.stdout
    assert safe_secret not in safe.stdout

    unsafe_env = tmp_path / "unsafe.env"
    unsafe_env.write_text(safe_env.read_text(encoding="utf-8").replace("https://avito.planam.ru", "http://localhost:3000").replace(safe_secret, "changeme"), encoding="utf-8")
    unsafe = subprocess.run(
        ["python", "scripts/validate_prod_env.py", str(unsafe_env)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert unsafe.returncode == 1
    assert "PROD ENV VALIDATION: FAIL" in unsafe.stdout
    assert "changeme" not in unsafe.stdout


def test_deploy_script_requires_explicit_expected_commit():
    text = (ROOT / "scripts" / "deploy-prod.ps1").read_text(encoding="utf-8")
    assert '[string]$ExpectedCommit = ""' in text
    assert "ExpectedCommit is required" in text
    assert 'ExpectedCommit = "3ad6a13"' not in text
