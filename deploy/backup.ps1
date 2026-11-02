# Manual backup on Windows (the "backup" service already takes one every day).
#   powershell -ExecutionPolicy Bypass -File deploy\backup.ps1 [-CopyTo E:\Yedek] [-List]
param([string]$CopyTo = "", [switch]$List)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($List) {
  docker compose exec -T backend sh -c 'ls -lh /backups/erp_*.tar 2>/dev/null || echo "Yedek yok"'
  exit $LASTEXITCODE
}
docker compose exec -T backend python -m app.cli backup
if ($LASTEXITCODE -ne 0) { throw "Yedekleme başarısız" }
if ($CopyTo) {
  New-Item -ItemType Directory -Force -Path $CopyTo | Out-Null
  $name = (docker compose exec -T backend sh -c 'ls -1t /backups/erp_*.tar | head -n1').Trim()
  docker compose cp "backend:$name" $CopyTo
  Write-Host "Kopyalandı: $CopyTo\$(Split-Path $name -Leaf)"
}
