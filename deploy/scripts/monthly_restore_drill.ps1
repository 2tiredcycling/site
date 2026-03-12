param(
    [Parameter(Mandatory=$true)][string]$BackupFile,
    [string]$ProjectRoot = "."
)

$resolvedProject = Resolve-Path $ProjectRoot
if (!(Test-Path $BackupFile)) {
    Write-Error "Backup file not found: $BackupFile"
    exit 1
}

$restoreDir = Join-Path $resolvedProject "tmp_restore_drill"
if (Test-Path $restoreDir) {
    Remove-Item -Recurse -Force $restoreDir
}
New-Item -ItemType Directory -Force -Path $restoreDir | Out-Null

Expand-Archive -Path $BackupFile -DestinationPath $restoreDir -Force

$dbOk = Test-Path (Join-Path $restoreDir "instance\app.db")
$uploadsOk = Test-Path (Join-Path $restoreDir "uploads\gpx")

if ($dbOk -and $uploadsOk) {
    Write-Output "Restore drill passed: database and uploads recovered."
    exit 0
}

Write-Error "Restore drill failed: missing database or uploads in restored package."
exit 1
