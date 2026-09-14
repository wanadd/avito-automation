param(
    [string]$ComposeFile = "docker-compose.prod.yml",
    [string]$EnvFile = ".env",
    [string]$ExpectedCommit = "",
    [switch]$AllowSharedIngressInstructions
)

$ErrorActionPreference = "Stop"

if (-not $ExpectedCommit) {
    throw "ExpectedCommit is required. Pass the commit being deployed with -ExpectedCommit <sha>."
}

$currentCommit = git rev-parse --short HEAD
if ($currentCommit -ne $ExpectedCommit) {
    throw "Unexpected commit $currentCommit. Expected $ExpectedCommit"
}

if (-not (Test-Path $EnvFile)) {
    throw "Production env file not found: $EnvFile"
}

python scripts/validate_prod_env.py $EnvFile

$envInfo = Get-Item $EnvFile
if (($envInfo.Attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
    throw "Env path is not a file: $EnvFile"
}

docker network inspect planam_ingress | Out-Null

Write-Output "Running backup"
pwsh -File scripts/backup.ps1 -ComposeFile $ComposeFile

Write-Output "Validating compose"
docker compose --env-file $EnvFile -f $ComposeFile config --quiet

Write-Output "Building images"
docker compose --env-file $EnvFile -f $ComposeFile build

Write-Output "Starting services"
docker compose --env-file $EnvFile -f $ComposeFile up -d postgres redis api web worker scheduler

Write-Output "Running migrations"
docker compose --env-file $EnvFile -f $ComposeFile exec -T api alembic upgrade head

Write-Output "Verifying health"
docker compose --env-file $EnvFile -f $ComposeFile exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health', timeout=10).read().decode())"
docker compose --env-file $EnvFile -f $ComposeFile exec -T web node -e "fetch('http://127.0.0.1:3000/health').then(r=>{console.log(r.status); if(!r.ok)process.exit(1)}).catch(e=>{console.error(e); process.exit(1)})"
docker compose --env-file $EnvFile -f $ComposeFile run --rm --no-deps --network planam_ingress web node -e "Promise.all([fetch('http://avito-automation-web:3000/'), fetch('http://avito-automation-api:8000/health')]).then(rs=>{console.log(rs.map(r=>r.status).join(',')); if(rs.some(r=>!r.ok))process.exit(1)}).catch(e=>{console.error(e); process.exit(1)})"
docker compose --env-file $EnvFile -f $ComposeFile ps

if (-not $AllowSharedIngressInstructions) {
    Write-Output "Shared nginx mutation is intentionally not automated. Follow docs/production-commissioning.md after existing-site safety checks."
}

Write-Output "DEPLOY: PASS"
