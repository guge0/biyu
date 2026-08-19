param(
    [string]$SourcePath = (Join-Path $PSScriptRoot "..\data"),
    [string]$DestinationRoot = "D:\biyu-data-replica",
    [ValidateRange(24, 168)][int]$HourlyRetentionHours = 72,
    [ValidateRange(30, 90)][int]$DailyRetentionDays = 31
)

$ErrorActionPreference = "Stop"

function Write-ReplicaStatus([hashtable]$Status) {
    $statusPath = Join-Path $DestinationRoot "status.json"
    if (Test-Path -LiteralPath $statusPath) {
        try {
            $previous = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if (-not $Status.ContainsKey("last_success") -or -not $Status.last_success) { $Status.last_success = $previous.last_success }
            if (-not $Status.ContainsKey("earliest_recovery") -or -not $Status.earliest_recovery) { $Status.earliest_recovery = $previous.earliest_recovery }
        } catch { }
    }
    $Status.updated_at = (Get-Date).ToUniversalTime().ToString("o")
    $Status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding utf8
}

function Get-ReplicaSnapshots {
    if (-not (Test-Path -LiteralPath $DestinationRoot)) { return @() }
    $items = @()
    Get-ChildItem -LiteralPath $DestinationRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match '^snapshot-(\d{8}T\d{6}Z)$') {
            $timestamp = [datetime]::ParseExact(
                $Matches[1],
                "yyyyMMdd'T'HHmmss'Z'",
                [Globalization.CultureInfo]::InvariantCulture,
                ([Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal)
            )
            $items += [pscustomobject]@{ Directory = $_; Timestamp = $timestamp }
        }
    }
    return @($items | Sort-Object Timestamp -Descending)
}

function Select-RetainedSnapshots([array]$Snapshots, [datetime]$NowUtc) {
    $hourCutoff = $NowUtc.AddHours(-$HourlyRetentionHours)
    $dayCutoff = $NowUtc.Date.AddDays(-$DailyRetentionDays)
    $seenHours = New-Object 'System.Collections.Generic.HashSet[string]'
    $seenDays = New-Object 'System.Collections.Generic.HashSet[string]'
    $kept = @()
    foreach ($item in $Snapshots) {
        if ($item.Timestamp -ge $hourCutoff) {
            if ($seenHours.Add($item.Timestamp.ToString("yyyyMMddHH"))) { $kept += $item }
        } elseif ($item.Timestamp -ge $dayCutoff) {
            if ($seenDays.Add($item.Timestamp.ToString("yyyyMMdd"))) { $kept += $item }
        }
    }
    return @($kept)
}

function Get-EarliestRecoveryDate([array]$Snapshots) {
    if (-not $Snapshots.Count) { return "" }
    return ($Snapshots | Sort-Object Timestamp | Select-Object -First 1).Timestamp.ToString("yyyy-MM-dd")
}

function Get-FileSha256([string]$Path) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
        } finally {
            [void]$stream.Dispose()
        }
    } finally {
        [void]$sha256.Dispose()
    }
}

function Get-RelativeHashMap([string]$Root) {
    $rootPath = (Resolve-Path -LiteralPath $Root).Path
    $map = @{}
    Get-ChildItem -LiteralPath $rootPath -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($rootPath.Length).TrimStart('\')
        $map[$relative] = Get-FileSha256 -Path $_.FullName
    }
    return $map
}

try {
    $source = (Resolve-Path -LiteralPath $SourcePath).Path
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Source data directory does not exist: $SourcePath" }
    New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $staging = Join-Path $DestinationRoot ".staging-$stamp"
    $snapshot = Join-Path $DestinationRoot "snapshot-$stamp"
    New-Item -ItemType Directory -Force -Path $staging | Out-Null

    # SourcePath is read-only throughout: this is a one-way copy, never a mirror.
    Copy-Item -LiteralPath $source -Destination (Join-Path $staging "data") -Recurse -Force
    $sourceHashes = Get-RelativeHashMap $source
    $copiedHashes = Get-RelativeHashMap (Join-Path $staging "data")
    if ($sourceHashes.Count -ne $copiedHashes.Count) { throw "SHA256 verification failed: file count differs" }
    foreach ($relative in $sourceHashes.Keys) {
        if (-not $copiedHashes.ContainsKey($relative) -or $sourceHashes[$relative] -ne $copiedHashes[$relative]) {
            throw "SHA256 verification failed: $relative"
        }
    }
    $sourceHashes | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $staging "sha256.json") -Encoding utf8
    Move-Item -LiteralPath $staging -Destination $snapshot

    $nowUtc = (Get-Date).ToUniversalTime()
    $snapshots = @(Get-ReplicaSnapshots)
    $retained = @(Select-RetainedSnapshots $snapshots $nowUtc)
    $retainedPaths = New-Object 'System.Collections.Generic.HashSet[string]'
    $retained | ForEach-Object { [void]$retainedPaths.Add($_.Directory.FullName) }
    $snapshots | Where-Object { -not $retainedPaths.Contains($_.Directory.FullName) } | ForEach-Object {
        Remove-Item -LiteralPath $_.Directory.FullName -Recurse -Force
    }
    $keptSnapshots = @(Get-ReplicaSnapshots)
    Write-ReplicaStatus @{
        last_success = $nowUtc.ToString("o")
        snapshot_count = $keptSnapshots.Count
        earliest_recovery = Get-EarliestRecoveryDate $keptSnapshots
        failed = $false
        last_error = ""
    }
    exit 0
}
catch {
    if (Test-Path -LiteralPath $DestinationRoot) {
        $keptSnapshots = @(Get-ReplicaSnapshots)
        Write-ReplicaStatus @{
            last_success = ""
            snapshot_count = $keptSnapshots.Count
            earliest_recovery = Get-EarliestRecoveryDate $keptSnapshots
            failed = $true
            last_error = $_.Exception.Message
        }
    }
    throw
}
