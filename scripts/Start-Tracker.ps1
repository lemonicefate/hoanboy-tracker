param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')))
& uv sync --frozen --no-dev
if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed.' }
if (-not (Test-Path -LiteralPath 'private/app/config.json')) {
    & uv run --no-dev python -m hoanboy init
    if ($LASTEXITCODE -ne 0) { throw 'Initialization failed.' }
}
& uv run --no-dev python -m hoanboy serve --port $Port
