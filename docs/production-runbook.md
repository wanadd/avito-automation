# Production Runbook

## First Deployment

1. Copy `.env.example` to `.env` on the host and replace placeholders.
2. Set `SESSION_SECRET` to a long random value.
3. Keep `POSTGRES_PASSWORD`, Telegram credentials, and any future marketplace credentials outside Git.
4. Run `docker compose -f docker-compose.prod.yml config`.
5. Start the stack with `docker compose -f docker-compose.prod.yml up -d --build`.
6. Run migrations once: `docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head`.
7. Create the first admin:
   `docker compose -f docker-compose.prod.yml exec -T api python -m app.cli create-operator admin --role ADMIN`
8. Verify `/health`, the web UI, login, database, Redis, worker, and scheduler.

## Routine Deployment

Use `scripts/deploy-prod.ps1`. It stops on backup, build, migration, or health failure and prints `DEPLOY: PASS` only after checks.

Do not run `docker compose down -v` during deployment.

## Backup

Run `scripts/backup.ps1`. Default retention is 7 daily backups. Backups include a PostgreSQL dump and manifest. Telegram session files are not included in plaintext backups; back them up manually with encryption if operationally required.

## Restore

1. Stop API, worker, scheduler, and web containers.
2. Keep PostgreSQL running.
3. Restore the selected `database.sql` with `psql`.
4. Run `alembic current`, then `alembic upgrade head` if needed.
5. Start API, worker, scheduler, and web.
6. Verify health, login, dashboard, and a publication dry-run.

## Worker Restart

`docker compose -f docker-compose.prod.yml restart worker`

Worker concurrency is the current single RQ worker process. Increase only after measuring Redis/PostgreSQL capacity.

## Scheduler Restart

`docker compose -f docker-compose.prod.yml restart scheduler`

Run one scheduler instance unless leader election is added.

## Migration Flow

Migrations run once per deploy from the API image. Do not run concurrent migrations.

## Health Verification

Check:

- `GET /health`
- `GET /api/v1/operator/system/health` after login
- `docker compose -f docker-compose.prod.yml ps`
- PostgreSQL healthcheck
- Redis healthcheck

## Incident Quick Checks

- API logs: `docker compose -f docker-compose.prod.yml logs api --tail=200`
- Worker logs: `docker compose -f docker-compose.prod.yml logs worker --tail=200`
- Scheduler logs: `docker compose -f docker-compose.prod.yml logs scheduler --tail=200`
- Open alerts in `/alerts`
- Failed jobs in `/publication`

## Avito Limitation

Live Avito mutation is disabled: `DISABLED_CONTRACT_INCOMPLETE`. Operators may prepare, dry-run, reconcile, and inspect jobs only.
