param(
    [string]$SnapshotPath = (Join-Path $PSScriptRoot '../private/bodyparm.json'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../private/profile')
)
$ErrorActionPreference = 'Stop'
$payload = Get-Content -LiteralPath $SnapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($payload.isSuccessful -ne $true -or $payload.isSelectQuery -ne $true) { throw 'Not a successful table read.' }
$columns = @($payload.tableInfos.title)
if (($columns | Select-Object -Unique).Count -ne $columns.Count) { throw 'Duplicate column names.' }
foreach ($row in $payload.rows) {
    if ($row.Count -ne $columns.Count) { throw 'Row width does not match schema.' }
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$profile = for ($i = 0; $i -lt $columns.Count; $i++) {
    $values = @($payload.rows | ForEach-Object { $_[$i].value })
    $filled = @($values | Where-Object { $null -ne $_ -and -not [string]::IsNullOrWhiteSpace("$_") })
    [pscustomobject]@{
        Field = $columns[$i]
        Primary = $payload.tableInfos[$i].isPrimary
        Types = (@($payload.rows | ForEach-Object { $_[$i].dataType } | Sort-Object -Unique) -join ',')
        Rows = $payload.rows.Count
        Filled = $filled.Count
        Missing = $payload.rows.Count - $filled.Count
        DistinctFilled = @($filled | Sort-Object -Unique).Count
        Zero = @($filled | Where-Object { "$_" -match '^0(\.0+)?$' }).Count
        TaiwanMobileFormat = @($filled | Where-Object { "$_" -match '^(09\d{8}|\+?8869\d{8})$' }).Count
    }
}
$profile | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'columns.csv') -NoTypeInformation -Encoding UTF8
$serializedRows = @($payload.rows | ForEach-Object { ConvertTo-Json -InputObject $_ -Depth 8 -Compress })
$summary = [ordered]@{
    CapturedProfileAt = [DateTimeOffset]::Now.ToString('o')
    Rows = $payload.rows.Count
    Columns = $columns.Count
    ExactDuplicateRows = $serializedRows.Count - @($serializedRows | Select-Object -Unique).Count
    PrimaryFields = @($payload.tableInfos | Where-Object isPrimary | ForEach-Object title)
    EmptyFields = @($profile | Where-Object Filled -eq 0 | ForEach-Object Field)
    PartiallyMissingFields = @($profile | Where-Object { $_.Filled -gt 0 -and $_.Missing -gt 0 } | ForEach-Object Field)
    AllZeroFields = @($profile | Where-Object { $_.Rows -gt 0 -and $_.Zero -eq $_.Rows } | ForEach-Object Field)
    CandidateIdentity = @($profile | Where-Object Field -in @('uid','username','userUid','time'))
    InputWeightEqualsResultWeight = 0
}
$inputIndex = [array]::IndexOf($columns, 'weight')
$resultIndex = [array]::IndexOf($columns, 'bhWeightKg')
if ($inputIndex -ge 0 -and $resultIndex -ge 0) {
    foreach ($row in $payload.rows) {
        $a = 0.0; $b = 0.0
        $style = [Globalization.NumberStyles]::Float
        $culture = [Globalization.CultureInfo]::InvariantCulture
        if ([double]::TryParse([string]$row[$inputIndex].value,$style,$culture,[ref]$a) -and
            [double]::TryParse([string]$row[$resultIndex].value,$style,$culture,[ref]$b) -and
            [math]::Abs($a - $b) -lt 0.000001) { $summary.InputWeightEqualsResultWeight++ }
    }
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding UTF8
$summary | ConvertTo-Json -Depth 6
