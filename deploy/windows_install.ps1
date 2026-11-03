# One-step install / update on Windows (Docker Desktop). Run KURULUM.bat in the project folder,
# or: powershell -ExecutionPolicy Bypass -File deploy\windows_install.ps1 [-Demo] [-Port 8080] [-NoBrowser]
#   -Demo       also load the demo projects (python -m app.cli seed)
#   -Port N     web port; default: ERP_HTTP_PORT from .env, else 80 (8080 if 80 is busy)
#   -NoBrowser  do not open the browser at the end
# Safe to run again: it keeps .env and the data volumes, rebuilds the images and restarts.
param([switch]$Demo, [int]$Port = 0, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$root = Get-Location

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "HATA: $msg" -ForegroundColor Red; exit 1 }

function RandomText([int]$len) {
  $chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
  $bytes = New-Object byte[] $len
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function PortBusy([int]$p) {
  # A port held by our own frontend container is fine (re-run / update)
  $own = docker ps --filter "name=parca-takip-frontend" --format "{{.Ports}}" 2>$null
  if ($own -match ":$p->") { return $false }
  $l = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  return [bool]$l
}

# Secrets inside: only Administrators, SYSTEM and the installing user may read the file (SIDs, so any Windows language works)
function LockDown([string]$path) {
  $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  & icacls $path /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" "*${me}:F" | Out-Null
}
# UTF-8 without BOM: Windows PowerShell 5.1 "-Encoding utf8" adds a BOM that breaks compose's .env parser
function WriteEnv([string[]]$lines) {
  [IO.File]::WriteAllLines((Join-Path $root ".env"), $lines, (New-Object System.Text.UTF8Encoding($false)))
  LockDown (Join-Path $root ".env")
}

function SetEnvValue([string[]]$lines, [string]$key, [string]$value) {
  if ($lines -match "^$key=") { return [string[]]($lines -replace "^$key=.*", "$key=$value") }
  return [string[]]($lines + "$key=$value")
}

function EnvValue([string[]]$lines, [string]$key) {
  $m = $lines | Where-Object { $_ -match "^$key=" } | Select-Object -First 1
  if ($m) { return ($m -replace "^$key=", "").Trim() }
  return ""
}

# ---------- 1. Docker ----------
Step "Docker kontrol ediliyor"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Fail "Docker bulunamadı. Docker Desktop'ı kurun (https://www.docker.com/products/docker-desktop/), bilgisayarı yeniden başlatın ve bu dosyayı tekrar çalıştırın."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $exe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
  if (Test-Path $exe) {
    Write-Host "Docker Desktop başlatılıyor..."
    Start-Process $exe | Out-Null
  }
  Write-Host "Docker'ın hazır olması bekleniyor (en çok 3 dakika)..."
  $deadline = (Get-Date).AddMinutes(3)
  do {
    Start-Sleep -Seconds 5
    docker info *> $null
  } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
  if ($LASTEXITCODE -ne 0) { Fail "Docker çalışmıyor. Docker Desktop'ı açın, 'Engine running' yazısını görünce tekrar deneyin." }
}
$os = (docker info --format "{{.OSType}}" 2>$null)
if ($os -ne "linux") {
  Fail "Docker Desktop Windows container modunda. Sistem tepsisindeki Docker simgesine sağ tıklayıp 'Switch to Linux containers' seçin."
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "'docker compose' bulunamadı. Docker Desktop'ı güncelleyin." }

# ---------- 2. .env ----------
Step "Ayar dosyası (.env)"
$newInstall = $false
if (-not (Test-Path .env)) {
  $newInstall = $true
  $lines = [string[]](Get-Content -Encoding UTF8 .env.example)
  $lines = SetEnvValue $lines "POSTGRES_PASSWORD" (RandomText 24)
  $lines = SetEnvValue $lines "ERP_JWT_SECRET" (RandomText 48)
  $lines = SetEnvValue $lines "ERP_ADMIN_PASSWORD" (RandomText 10)
  Write-Host ".env oluşturuldu: veritabanı şifresi, oturum anahtarı ve yönetici şifresi rastgele üretildi."
} else {
  $lines = [string[]](Get-Content -Encoding UTF8 .env)
  Write-Host "Mevcut .env kullanılıyor."
}

if ($Port -le 0) {
  $p = EnvValue $lines "ERP_HTTP_PORT"
  if ($p) { $Port = [int]$p } else { $Port = 80 }
}
if (PortBusy $Port) {
  $old = $Port
  foreach ($c in 8080, 8081, 8088, 8090, 8888) { if (-not (PortBusy $c)) { $Port = $c; break } }
  if ($Port -eq $old) { Fail "Port $old dolu ve yedek portlar da dolu. -Port ile boş bir port verin." }
  Write-Host "Port $old başka bir program tarafından kullanılıyor, $Port kullanılacak." -ForegroundColor Yellow
}
$lines = SetEnvValue $lines "ERP_HTTP_PORT" "$Port"
WriteEnv $lines

# ---------- 3. Build and start ----------
Step "İmajlar derleniyor ve sistem başlatılıyor (ilk kurulumda internet gerekir, birkaç dakika sürebilir)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "docker compose up başarısız. Ayrıntı: docker compose logs" }

Step "Sistemin açılması bekleniyor"
$ok = $false
$deadline = (Get-Date).AddMinutes(5)
while (-not $ok -and (Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:$Port/api/health"
    $ok = ($r.StatusCode -eq 200)
  } catch { }
}
if (-not $ok) { Fail "Sistem 5 dakikada açılmadı. Ayrıntı: docker compose logs backend" }
docker compose ps

if ($Demo) {
  Step "Demo projeler yükleniyor"
  docker compose exec -T backend python -m app.cli seed
}

# ---------- 4. Firewall ----------
Step "Güvenlik duvarı"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
$ruleName = "Parca Takip ERP ($Port)"
if ($isAdmin) {
  if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
  }
  Write-Host "TCP $Port portu yerel ağa açık."
} else {
  Write-Host "Diğer bilgisayarların erişmesi için yönetici PowerShell'de bir kez çalıştırın:" -ForegroundColor Yellow
  Write-Host "  New-NetFirewallRule -DisplayName `"$ruleName`" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow"
}

# ---------- 5. Done ----------
$suffix = ""
if ($Port -ne 80) { $suffix = ":$Port" }
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.InterfaceAlias -notmatch "vEthernet|WSL|Docker|Loopback" } |
       Select-Object -ExpandProperty IPAddress
Write-Host ""
Write-Host "Kurulum tamam." -ForegroundColor Green
Write-Host "  Bu bilgisayardan : http://localhost$suffix"
foreach ($ip in $ips) { Write-Host "  Yerel ağdan      : http://$ip$suffix" }
if ($newInstall) {
  Write-Host "  Kullanıcı adı    : $(EnvValue $lines 'ERP_ADMIN_USER')"
  Write-Host "  İlk şifre        : $(EnvValue $lines 'ERP_ADMIN_PASSWORD')   (.env dosyasında da yazılı; girişten sonra değiştirin)"
}
if (-not $NoBrowser) { Start-Process "http://localhost$suffix" | Out-Null }
