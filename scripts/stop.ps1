$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot
try {
    docker compose down
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
