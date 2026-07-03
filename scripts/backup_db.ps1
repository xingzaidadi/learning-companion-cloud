$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dataDir = Join-Path $root "data"
$backupDir = Join-Path $root "backups"
$dbPath = Join-Path $dataDir "learning.db"

if (!(Test-Path $dbPath)) {
  Write-Host "No database found: $dbPath"
  exit 0
}

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $backupDir "learning_$timestamp.db"
Copy-Item -Path $dbPath -Destination $target -Force
Write-Host "Backup created: $target"
