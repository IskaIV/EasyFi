$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Spec = Join-Path $PSScriptRoot "EasyFi.spec"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "EasyFi's .venv was not found. Create it before building."
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --clean --noconfirm $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$Executable = Join-Path $ProjectRoot "dist\EasyFi.exe"
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "The build completed without producing dist\EasyFi.exe."
}

Write-Host "Built $Executable"

