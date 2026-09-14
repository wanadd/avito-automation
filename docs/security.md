# Security Notes

## Secrets

Do not commit `.env`, Telegram sessions, credentials, private keys, cookies, or tokens. `.env.example` contains placeholders only.

## Sessions

The operator UI uses an HttpOnly session cookie and a separate CSRF cookie/header. Production should set `COOKIE_SECURE=true` and serve through HTTPS.

## Operator Passwords

Passwords are hashed with Argon2id. Create operators with `python -m app.cli create-operator`. No default password is stored in the repository.

## Roles

- `VIEWER`: read-only.
- `OPERATOR`: review, dry-run, retry/cancel, recalculate, reconcile.
- `ADMIN`: operator management, backup smoke, settings, and all operator actions.

Frontend button hiding is not authorization. Backend dependencies enforce roles.

## Telegram

Telegram API values and session files must stay outside Git. The ordinary backup script excludes Telegram sessions. Use encrypted manual backup if session loss would be operationally expensive.

## Database and Redis

Production compose does not publish PostgreSQL or Redis ports. Keep them on the internal Docker network unless there is a deliberate, secured operations path.

## Backups

Backups may contain operational data. Store them with restricted filesystem permissions and encrypted off-host storage when used outside the server.

## Frontend

Only public-safe values use `NEXT_PUBLIC_*`. The frontend stores no auth token in localStorage and renders JSON payloads as escaped text.

## Avito

No live Avito OAuth, browser automation, scraping, or mutation is implemented. Real mutation remains blocked with `DISABLED_CONTRACT_INCOMPLETE`.
