$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv (Join-Path $projectRoot '.venv')
    & $pythonPath -m pip install -r (Join-Path $projectRoot 'backend\requirements.txt')
}
Push-Location $projectRoot
try {
    & $pythonPath scripts\init_local.py
    & $pythonPath backend\manage.py migrate
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
    if (-not (Test-Path -LiteralPath 'frontend\node_modules\next\package.json')) {
        Push-Location frontend
        try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' } } finally { Pop-Location }
    }
    if (-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $pythonPath -ArgumentList @('backend\manage.py','runserver','127.0.0.1:8000','--noreload') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'backend.log') -RedirectStandardError (Join-Path $projectRoot 'backend-error.log')
    }
    if (-not (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c','npm run dev') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'frontend.log') -RedirectStandardError (Join-Path $projectRoot 'frontend-error.log')
    }
    Write-Output 'Local app: http://localhost:3000. Logs are in the project folder.'
} finally { Pop-Location }
