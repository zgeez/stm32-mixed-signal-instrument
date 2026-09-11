$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Missing .venv. Install desktop[dev] in the repository virtual environment.'
}
Push-Location $repoRoot
try {
    & $pythonExe -m pytest -p no:cacheprovider -c desktop/pyproject.toml desktop/tests
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
    & $pythonExe -m ruff check desktop
    if ($LASTEXITCODE -ne 0) { throw 'ruff check failed' }
    & $pythonExe -m ruff format --check desktop
    if ($LASTEXITCODE -ne 0) { throw 'ruff format failed' }
} finally {
    Pop-Location
}
