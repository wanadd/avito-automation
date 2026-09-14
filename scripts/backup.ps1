param(
    [string]$ComposeFile = "docker-compose.prod.yml",
    [string]$BackupRoot = "runtime/backups",
    [int]$RetentionDays = 7
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $BackupRoot $stamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

docker compose -f $ComposeFile exec -T postgres pg_dump -U avito avito_automation | Set-Content -Encoding UTF8 (Join-Path $target "database.sql")

$manifest = @{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    includes = @("postgres database dump")
    excludes = @(".env", "Telegram session files", "private keys")
    telegram_session_backup = "manual encrypted backup only"
    retention_days = $RetentionDays
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $target "manifest.json")

Get-ChildItem $BackupRoot -Directory |
    Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item -Recurse -Force

Write-Output "BACKUP: PASS $target"
