param(
    [string]$ComposeFile = "docker-compose.prod.yml"
)

$ErrorActionPreference = "Stop"

Write-Output "Running backup"
pwsh -File scripts/backup.ps1 -ComposeFile $ComposeFile

Write-Output "Building images"
docker compose -f $ComposeFile build

Write-Output "Starting services"
docker compose -f $ComposeFile up -d

Write-Output "Running migrations"
docker compose -f $ComposeFile exec -T api alembic upgrade head

Write-Output "Verifying health"
docker compose -f $ComposeFile exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health', timeout=10).read().decode())"
docker compose -f $ComposeFile ps

Write-Output "DEPLOY: PASS"
