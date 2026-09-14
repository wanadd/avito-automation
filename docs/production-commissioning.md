# Production Commissioning: Shared Ingress

Target domain: `avito.planam.ru`

Target VPS: shared Ubuntu 24.04 host that already runs PLANAM Food and PlanAm_money.

## Topology

```text
Internet
  -> ai-food-family-nginx-1
  -> external Docker network: planam_ingress
  -> avito-automation-web / avito-automation-api
  -> avito_automation_prod_net
  -> postgres / redis / worker / scheduler
```

Avito's production compose does not start its own nginx by default. The `nginx` service is reserved for standalone deployments through the `standalone-ingress` Compose profile.

## Local Deployment Identity

Use:

```bash
COMPOSE_PROJECT_NAME=avito_automation_prod
```

The production services are expected to be addressed through Docker DNS aliases on `planam_ingress`:

- `avito-automation-web:3000`
- `avito-automation-api:8000`

PostgreSQL and Redis are not attached to `planam_ingress` and must not publish host ports.

The web container must run standalone Next.js on `0.0.0.0:3000`:

```env
HOSTNAME=0.0.0.0
PORT=3000
```

Use `/health` for web process health checks. Do not use `/` as a health check because `/` is the authenticated operator dashboard entrypoint and anonymous users are redirected to `/login`.

## Production Env

Create `/var/www/avito-automation/.env` from `.env.production.example`. Do not commit it.

Required permission:

```bash
chmod 600 /var/www/avito-automation/.env
```

Validate before deployment:

```bash
python scripts/validate_prod_env.py /var/www/avito-automation/.env
```

The validator rejects empty critical secrets, placeholder secrets, localhost public URLs, non-HTTPS production URLs, and domains other than `avito.planam.ru`.

Production `ALLOWED_HOSTS` must include both the public host and required internal production names:

```env
ALLOWED_HOSTS=avito.planam.ru,127.0.0.1,localhost,api,avito-automation-api
```

Do not use wildcard hosts.

## Deployment Script

The deploy script requires the commit being deployed to be supplied explicitly:

```powershell
pwsh -File scripts/deploy-prod.ps1 -EnvFile .env -ExpectedCommit <commit-sha>
```

This keeps commit verification deterministic without baking stale SHAs into the repository.

## Bootstrap Nginx

Before the TLS certificate exists, mount:

```text
/var/www/avito-automation/deploy/nginx/avito.planam.ru.bootstrap.conf
  -> /etc/nginx/conf.d/avito.planam.ru.conf:ro
```

This bootstrap config only listens on port 80, serves `/.well-known/acme-challenge/` from `/var/www/certbot`, and does not reference TLS files.

## Certificate

Do not install host certbot. Use the existing Docker certbot volumes:

```bash
docker run --rm \
  -v ai-food-family_certbot_certs:/etc/letsencrypt \
  -v ai-food-family_certbot_www:/var/www/certbot \
  certbot/certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  -d avito.planam.ru \
  --email admin@planam.ru \
  --agree-tos \
  --no-eff-email
```

Run this only after DNS for `avito.planam.ru` resolves to the VPS.

## Final HTTPS Nginx

After the certificate exists, switch the shared nginx bind mount to:

```text
/var/www/avito-automation/deploy/nginx/avito.planam.ru.conf.template
  -> /etc/nginx/conf.d/avito.planam.ru.conf:ro
```

The final config:

- redirects HTTP to HTTPS
- serves ACME challenge over HTTP
- uses `/etc/letsencrypt/live/avito.planam.ru/fullchain.pem`
- uses `/etc/letsencrypt/live/avito.planam.ru/privkey.pem`
- proxies `/api/` and `/health` to `avito-automation-api:8000`
- proxies `/` to `avito-automation-web:3000`
- uses Docker resolver `127.0.0.11 valid=10s ipv6=off`
- uses variable upstreams instead of static `upstream {}` blocks

Because Docker bind mounts are resolved when the container is created, switching bootstrap to final config requires recreating the shared nginx container, not only reloading nginx.

## Shared Nginx Safety Procedure

Before changing the shared ingress:

```bash
stamp="$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "/var/backups/avito-shared-ingress/$stamp"
cp /var/www/ai-food-family/docker-compose.prod.yml "/var/backups/avito-shared-ingress/$stamp/"
cp -a /var/www/ai-food-family/deploy/nginx "/var/backups/avito-shared-ingress/$stamp/nginx"
curl -I https://planam.ru
curl -I https://dengi.planam.ru
```

Add the Avito bind mount to the existing shared nginx service in `/var/www/ai-food-family/docker-compose.prod.yml`. Do not edit other PLANAM services.

After every nginx change:

```bash
docker compose -f /var/www/ai-food-family/docker-compose.prod.yml exec nginx nginx -t
curl -I https://planam.ru
curl -I https://dengi.planam.ru
```

If either existing site fails, rollback immediately.

## Rollback

Restore only the shared nginx compose/config backup:

```bash
cp /var/backups/avito-shared-ingress/<stamp>/docker-compose.prod.yml /var/www/ai-food-family/docker-compose.prod.yml
rm -f /var/www/ai-food-family/deploy/nginx/avito.planam.ru.conf
docker compose -f /var/www/ai-food-family/docker-compose.prod.yml up -d --force-recreate nginx
docker compose -f /var/www/ai-food-family/docker-compose.prod.yml exec nginx nginx -t
curl -I https://planam.ru
curl -I https://dengi.planam.ru
```

Do not restart unrelated databases or applications during rollback.

## Avito Guard

Live Avito mutation remains disabled. Expected operational values stay:

- `DISABLED_CONTRACT_INCOMPLETE`
- `AVITO_CONTRACT_INCOMPLETE`

Do not configure Avito credentials during this phase.
