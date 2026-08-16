$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"

if (-not (Test-Path $envFile)) {
    Write-Host "Create .env by copying .env.example, then set NEO4J_PASSWORD and OPENROUTER_API_KEY."
    exit 1
}

Push-Location $projectRoot
try {
    docker compose up --build -d
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
