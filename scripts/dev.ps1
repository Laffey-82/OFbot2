param([switch]$SkipInstall)

$ErrorActionPreference = "Stop"

if (-not $SkipInstall) {
  Write-Host "==> Install dependencies"
  py -m pip install -q -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

Write-Host "==> Syntax compile check"
py -m compileall -q app plugins main.py tests scripts
if ($LASTEXITCODE -ne 0) { throw "compileall failed" }

Write-Host "==> Ruff static check"
py -m ruff check app plugins main.py tests scripts
if ($LASTEXITCODE -ne 0) { throw "ruff check failed" }

Write-Host "==> Unit tests"
py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

Write-Host "==> E2E smoke"
py scripts/e2e_smoke.py
if ($LASTEXITCODE -ne 0) { throw "e2e smoke failed" }

Write-Host "All checks passed"
