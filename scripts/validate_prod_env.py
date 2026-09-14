from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


REQUIRED = {
    "APP_ENV",
    "DOMAIN",
    "APP_BASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
    "SESSION_SECRET",
    "COOKIE_SECURE",
    "ALLOWED_HOSTS",
    "CORS_ORIGINS",
    "NEXT_PUBLIC_API_BASE_URL",
    "COMPOSE_PROJECT_NAME",
}

BAD_SECRET_PATTERNS = (
    "change",
    "changeme",
    "password",
    "default",
    "secret",
    "local_only",
    "example",
    "placeholder",
)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid env line without '=': {raw_line!r}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_bad_secret(value: str) -> bool:
    lowered = value.lower()
    return any(pattern in lowered for pattern in BAD_SECRET_PATTERNS) or bool(re.fullmatch(r"[<>{}\s-]*", value))


def require_https(name: str, value: str, errors: list[str]) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append(f"{name} must be an HTTPS URL")
    if "localhost" in value or "127.0.0.1" in value:
        errors.append(f"{name} must not use localhost in production")


def validate(values: dict[str, str], expected_domain: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(key for key in REQUIRED if not values.get(key))
    errors.extend(f"{key} is required" for key in missing)

    if values.get("APP_ENV") != "production":
        errors.append("APP_ENV must be production")
    if values.get("DOMAIN") != expected_domain:
        errors.append(f"DOMAIN must be {expected_domain}")
    if values.get("COOKIE_SECURE", "").lower() != "true":
        errors.append("COOKIE_SECURE must be true")
    if values.get("COMPOSE_PROJECT_NAME") != "avito_automation_prod":
        errors.append("COMPOSE_PROJECT_NAME must be avito_automation_prod")
    allowed_hosts = {item.strip() for item in values.get("ALLOWED_HOSTS", "").split(",") if item.strip()}
    if "*" in allowed_hosts:
        errors.append("ALLOWED_HOSTS must not use wildcard in production")
    required_hosts = {expected_domain, "127.0.0.1", "localhost", "api", "avito-automation-api"}
    missing_hosts = sorted(required_hosts - allowed_hosts)
    if missing_hosts:
        errors.append("ALLOWED_HOSTS missing required production/internal hostnames")

    for name in ("APP_BASE_URL", "NEXT_PUBLIC_API_BASE_URL"):
        value = values.get(name)
        if value:
            require_https(name, value, errors)
            if urlparse(value).netloc != expected_domain:
                errors.append(f"{name} must point to {expected_domain}")

    for name in ("POSTGRES_PASSWORD", "SESSION_SECRET"):
        value = values.get(name, "")
        if len(value) < 32:
            errors.append(f"{name} must be at least 32 characters")
        if is_bad_secret(value):
            errors.append(f"{name} is not production-safe")

    database_url = values.get("DATABASE_URL", "")
    if "localhost" in database_url or "127.0.0.1" in database_url:
        errors.append("DATABASE_URL must not use localhost in production")
    if values.get("POSTGRES_PASSWORD") and values["POSTGRES_PASSWORD"] not in database_url:
        errors.append("DATABASE_URL must include the configured POSTGRES_PASSWORD")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate avito-automation production env without printing secrets.")
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--domain", default="avito.planam.ru")
    args = parser.parse_args()

    try:
        values = parse_env(args.env_file)
    except Exception as exc:
        print(f"PROD ENV VALIDATION: FAIL ({exc})")
        return 1

    errors = validate(values, args.domain)
    if errors:
        print("PROD ENV VALIDATION: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PROD ENV VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
