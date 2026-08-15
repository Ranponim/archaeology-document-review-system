param(
    [ValidateRange(5, 300)]
    [int] $TimeoutSeconds = 60,
    [ValidatePattern('^https?://[^\s]+$')]
    [string] $BaseUrl = 'http://localhost:8080',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
    [string] $ComposeProjectName = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$composePrefix = @('compose')
if ($ComposeProjectName) {
    $composePrefix += @('-p', $ComposeProjectName)
}

function Stop-HealthCheck([string] $ServiceName) {
    [Console]::Error.WriteLine($ServiceName)
    exit 1
}

function Invoke-Compose([string[]] $Arguments) {
    $output = & docker @composePrefix @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'compose check failed'
    }
    return $output
}

Push-Location $projectRoot
try {
    try {
        $running = @(Invoke-Compose @('ps', '--status', 'running', '--services'))
        foreach ($service in @('web', 'worker', 'neo4j', 'redis')) {
            if ($running -notcontains $service) {
                Stop-HealthCheck $service
            }
        }
    }
    catch {
        Stop-HealthCheck 'compose'
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $webReady = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl.TrimEnd('/') + '/') -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                $webReady = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $webReady) {
        Stop-HealthCheck 'web'
    }

    try {
        $health = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + '/health') -TimeoutSec 3
        if ($health.status -ne 'ok') {
            Stop-HealthCheck 'api'
        }
    }
    catch {
        Stop-HealthCheck 'api'
    }

    try {
        $null = Invoke-Compose @(
            'exec', '-T', 'neo4j', 'sh', '-c',
            'cypher-shell -u "${NEO4J_AUTH%%/*}" -p "${NEO4J_AUTH#*/}" "RETURN 1;" >/dev/null'
        )
    }
    catch {
        Stop-HealthCheck 'neo4j'
    }

    try {
        $redisReply = @(Invoke-Compose @('exec', '-T', 'redis', 'redis-cli', '--raw', 'ping'))
        if (($redisReply -join '').Trim() -ne 'PONG') {
            Stop-HealthCheck 'redis'
        }
    }
    catch {
        Stop-HealthCheck 'redis'
    }

    Write-Host 'healthy'
    exit 0
}
finally {
    Pop-Location
}
