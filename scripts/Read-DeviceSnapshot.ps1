param(
    [ValidatePattern('^192\.168\.1\.102$')]
    [string]$DeviceAddress = '192.168.1.102'
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$destination = Join-Path $root ('private/snapshots/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$base = 'http://' + $DeviceAddress + ':8080/'
foreach ($request in @(
    @{Route='getTableList?database=heer_scale.db'; File='table-list.json'},
    @{Route='getAllDataFromTheTable?tableName=bodyparm'; File='bodyparm.json'}
)) {
    $target = Join-Path $destination $request.File
    & curl.exe --noproxy '*' --connect-timeout 5 --max-time 15 --fail --silent --show-error --output $target ($base + $request.Route)
    if ($LASTEXITCODE -ne 0) { throw 'Device read failed. Incomplete snapshot remains in private storage.' }
    $response = Get-Content -LiteralPath $target -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($response.isSuccessful -ne $true) { throw 'Device did not return a successful result.' }
}
[ordered]@{
    CapturedAt = [DateTimeOffset]::Now.ToString('o')
    Database = 'heer_scale.db'
    Table = 'bodyparm'
    Sha256 = (Get-FileHash -LiteralPath (Join-Path $destination 'bodyparm.json') -Algorithm SHA256).Hash
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination 'manifest.json') -Encoding UTF8
& (Join-Path $PSScriptRoot 'Inspect-DeviceSnapshot.ps1') -SnapshotPath (Join-Path $destination 'bodyparm.json') -OutputDirectory (Join-Path $destination 'profile')
Write-Output ('Private snapshot: ' + $destination)
