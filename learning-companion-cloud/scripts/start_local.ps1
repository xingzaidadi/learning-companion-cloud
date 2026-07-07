$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (!(Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

python -m pip install -r requirements.txt
$env:APP_HOST = if ($env:APP_HOST) { $env:APP_HOST } else { "127.0.0.1" }
python -m uvicorn backend.app:app --host $env:APP_HOST --port 8000
