# Run on the OFFLINE Windows server (Docker Desktop) inside the copied dist-offline folder:
# loads the images and starts the system without internet.
#   powershell -ExecutionPolicy Bypass -File deploy\offline_import.ps1 [-Tar parca-takip-images-1.0.0.tar]
param([string]$Tar = "")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $Tar) {
  $f = Get-ChildItem -Path . , dist-offline -Filter "parca-takip-images-*.tar" -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($f) { $Tar = $f.FullName }
}
if (-not $Tar -or -not (Test-Path $Tar)) { throw "İmaj dosyası bulunamadı (parca-takip-images-*.tar)" }

$sumFile = "$Tar.sha256"
if (Test-Path $sumFile) {
  $expected = ((Get-Content $sumFile -Raw).Trim() -split "\s+")[0].ToLower()
  $actual = (Get-FileHash -Algorithm SHA256 $Tar).Hash.ToLower()
  if ($expected -ne $actual) { throw "Sağlama toplamı tutmuyor, dosya bozuk" }
}

Write-Host "İmajlar yükleniyor: $Tar"
docker load -i $Tar
if ($LASTEXITCODE -ne 0) { throw "docker load başarısız" }

$Tag = [IO.Path]::GetFileNameWithoutExtension($Tar) -replace "^parca-takip-images-", ""
if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host ".env oluşturuldu. Şifreleri değiştirip bu betiği tekrar çalıştırın."
  exit 0
}
$envText = @(Get-Content -Encoding UTF8 .env)
if ($envText -match "^ERP_TAG=") {
  $envText = $envText -replace "^ERP_TAG=.*", "ERP_TAG=$Tag"
} else {
  $envText += "ERP_TAG=$Tag"
}
# UTF-8 without BOM: Windows PowerShell 5.1 "-Encoding utf8" adds a BOM that breaks compose's .env parser
[IO.File]::WriteAllLines((Join-Path (Get-Location) ".env"), [string[]]$envText, (New-Object System.Text.UTF8Encoding($false)))

docker compose up -d --no-build
if ($LASTEXITCODE -ne 0) { throw "docker compose up başarısız" }
docker compose ps
$port = (($envText | Where-Object { $_ -match "^ERP_HTTP_PORT=" }) -replace "^ERP_HTTP_PORT=", "")
if (-not $port) { $port = "80" }
Write-Host "Kurulum tamam. Tarayıcıdan http://SUNUCU_IP:$port adresini açın."
