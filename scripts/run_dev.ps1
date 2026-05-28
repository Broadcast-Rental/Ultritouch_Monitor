# Local development: Ember poller + API (two windows) or run in background.
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path config.yaml)) {
    Copy-Item config.example.yaml config.yaml
}
New-Item -ItemType Directory -Force -Path data | Out-Null

Write-Host "Start in separate terminals:"
Write-Host "  node ember/poller.mjs"
Write-Host "  python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8080"
