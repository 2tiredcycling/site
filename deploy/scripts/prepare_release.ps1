param(
    [Parameter(Mandatory = $true)]
    [string]$ReleasesRoot,

    [Parameter(Mandatory = $true)]
    [string]$CurrentRelease,

    [string]$PreviousRelease = "",

    [string]$ManifestPath = "",

    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-AbsolutePath {
    param([string]$PathText)
    $item = Get-Item -LiteralPath $PathText
    return $item.FullName
}

if (-not $ManifestPath) {
    $ManifestPath = Join-Path $PSScriptRoot "release_copy_manifest.txt"
}

$manifestFull = Resolve-AbsolutePath -PathText $ManifestPath
$releasesRootFull = Resolve-AbsolutePath -PathText $ReleasesRoot
$currentPath = Join-Path $releasesRootFull $CurrentRelease

if (-not (Test-Path -LiteralPath $currentPath)) {
    throw "Current release folder not found: $currentPath"
}

if (-not $PreviousRelease) {
    $candidate = Get-ChildItem -LiteralPath $releasesRootFull -Directory |
        Where-Object { $_.Name -ne $CurrentRelease } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "Cannot auto-detect previous release under: $releasesRootFull"
    }
    $PreviousRelease = $candidate.Name
}

$previousPath = Join-Path $releasesRootFull $PreviousRelease
if (-not (Test-Path -LiteralPath $previousPath)) {
    throw "Previous release folder not found: $previousPath"
}

$entries = Get-Content -LiteralPath $manifestFull |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }

if (-not $entries -or $entries.Count -eq 0) {
    throw "Manifest has no entries: $manifestFull"
}

$requiredItems = @(".env", "deploy/nginx.conf", "deploy/certs")
foreach ($required in $requiredItems) {
    if ($entries -notcontains $required) {
        throw "Required manifest entry missing: $required"
    }
    $requiredSource = Join-Path $previousPath $required
    if (-not (Test-Path -LiteralPath $requiredSource)) {
        throw "Required source missing in previous release: $requiredSource"
    }
}

$mode = if ($Apply) { "APPLY" } else { "DRY-RUN" }
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $currentPath "deploy_sync_$timestamp.log"

"[$mode] releases_root=$releasesRootFull" | Out-File -FilePath $logFile -Encoding utf8
"[$mode] previous=$previousPath" | Add-Content -LiteralPath $logFile
"[$mode] current=$currentPath" | Add-Content -LiteralPath $logFile
"[$mode] manifest=$manifestFull" | Add-Content -LiteralPath $logFile

$copied = 0
$skipped = 0

foreach ($relative in $entries) {
    $source = Join-Path $previousPath $relative
    $target = Join-Path $currentPath $relative

    if (-not (Test-Path -LiteralPath $source)) {
        "[SKIP] missing source: $relative" | Tee-Object -FilePath $logFile -Append
        $skipped++
        continue
    }

    if (-not $Apply) {
        "[PLAN] $relative" | Tee-Object -FilePath $logFile -Append
        continue
    }

    $targetParent = Split-Path -Parent $target
    if ($targetParent -and -not (Test-Path -LiteralPath $targetParent)) {
        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
    }

    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }

    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    "[COPY] $relative" | Tee-Object -FilePath $logFile -Append
    $copied++
}

"[DONE] copied=$copied skipped=$skipped mode=$mode" | Tee-Object -FilePath $logFile -Append

if (-not $Apply) {
    Write-Host "Dry-run complete. Add -Apply to execute copy."
}
