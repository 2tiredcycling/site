param(
    [string]$ProjectRoot = ".",
    [string]$BackupDir = "backups"
)

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resolvedProject = Resolve-Path $ProjectRoot
$targetDir = Join-Path $resolvedProject $BackupDir
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$dbFile = Join-Path $resolvedProject "instance\app.db"
$uploadDir = Join-Path $resolvedProject "uploads\gpx"
$outFile = Join-Path $targetDir "backup_$timestamp.zip"

if (!(Test-Path $dbFile)) {
    Write-Error "Database file not found: $dbFile"
    exit 1
}

Compress-Archive -Path $dbFile, $uploadDir -DestinationPath $outFile -Force
Write-Output "Backup created: $outFile"
