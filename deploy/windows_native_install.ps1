# Docker-free install / update on Windows: Python 3.12 + SQLite, one process, started at boot by
# the Task Scheduler (task "ParcaTakipERP", runs as SYSTEM, no user needs to sign in).
# Run KURULUM_DOCKERSIZ.bat in the project folder, or as administrator:
#   powershell -ExecutionPolicy Bypass -File deploy\windows_native_install.ps1 [-DataDir D:\ParcaTakipVeri] [-Port 8080] [-Demo] [-NoBrowser]
#   -DataDir    database, uploaded files, backups, log and a copy of the settings (default C:\ParcaTakipVeri)
#   -Port N     web port; default: the previous port, else 80 (8080 if 80 is busy)
#   -Demo       also load the demo projects
# Safe to run again (update): keeps the data and settings, reinstalls packages, rebuilds the UI, restarts.
param([string]$DataDir = "C:\ParcaTakipVeri", [int]$Port = 0, [switch]$Demo, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
$backend = Join-Path $root "backend"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
$envFile = Join-Path $backend ".env"
$TaskName = "ParcaTakipERP"

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "HATA: $msg" -ForegroundColor Red; exit 1 }
function Run($exe, [string[]]$argv, $what) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { Fail "$what başarısız (çıkış kodu $LASTEXITCODE)" }
}
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function RandomText([int]$len) {
  $chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
  $bytes = New-Object byte[] $len
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
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
# UTF-8 without BOM, so the settings parser reads the first key correctly
function WriteLines([string]$path, [string[]]$lines) {
  [IO.File]::WriteAllLines($path, $lines, (New-Object System.Text.UTF8Encoding($false)))
}
function WingetInstall($id, $what) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail "$what bulunamadı ve winget yok. $what'ı elle kurun ('Install for all users' ve 'Add to PATH' seçili), sonra tekrar çalıştırın."
  }
  Write-Host "$what kuruluyor (winget)..."
  & winget install --id $id -e --scope machine --silent --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    # Some packages have no machine-scope installer variant; retry with the default scope
    & winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
  }
  RefreshPath
}
function FindPython312 {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    # PowerShell 5.1 turns redirected native stderr into a terminating error under "Stop"
    $ErrorActionPreference = "Continue"
    $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -and $p) { return "$p".Trim() }
  }
  foreach ($c in "$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") {
    if (Test-Path $c) { return $c }
  }
  return $null
}
function StopServer {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  }
  # The task may leave the python child running: stop every "app.cli serve" process
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*app.cli serve*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
}
function PortBusy([int]$p) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
}

# ---------- 0. Administrator ----------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "Yönetici olarak çalıştırın (KURULUM_DOCKERSIZ.bat izin ister)." }

# ---------- 1. Python 3.12 ----------
Step "Python 3.12"
$py = FindPython312
if (-not $py) {
  WingetInstall "Python.Python.3.12" "Python 3.12"
  $py = FindPython312
  if (-not $py) { Fail "Python 3.12 kurulamadı. https://www.python.org/downloads/ adresinden 3.12 sürümünü kurun." }
}
if ($py -like "$env:LOCALAPPDATA*") {
  Write-Host "Uyarı: Python yalnızca bu kullanıcı için kurulu. Açılışta SYSTEM hesabı çalıştıracağı için" -ForegroundColor Yellow
  Write-Host "'Install for all users' seçeneğiyle yeniden kurmanız önerilir." -ForegroundColor Yellow
}
Write-Host "Python: $py"

# ---------- 2. Stop a running copy (update) ----------
StopServer

# ---------- 3. Backend packages ----------
Step "Python paketleri kuruluyor"
if (-not (Test-Path $venvPy)) { Run $py @("-m", "venv", (Join-Path $backend ".venv")) "Sanal ortam oluşturma" }
Run $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip") "pip güncelleme"
Run $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", (Join-Path $backend "requirements.txt")) "Paket kurulumu"

# ---------- 4. Frontend build ----------
Step "Web arayüzü derleniyor"
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  WingetInstall "OpenJS.NodeJS.LTS" "Node.js"
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node.js kurulamadı. https://nodejs.org adresinden LTS sürümünü kurun." }
}
Push-Location (Join-Path $root "frontend")
try {
  Run "npm" @("ci", "--no-audit", "--no-fund") "npm ci"
  Run "npm" @("run", "build") "Arayüz derleme"
} finally { Pop-Location }

# ---------- 5. Settings ----------
Step "Ayarlar"
$DataDir = $DataDir.TrimEnd("\")
New-Item -ItemType Directory -Force -Path $DataDir, "$DataDir\data", "$DataDir\yedek" | Out-Null
$savedEnv = Join-Path $DataDir "ayarlar.env"
$newInstall = $false
if (-not (Test-Path $envFile) -and (Test-Path $savedEnv)) {
  Copy-Item $savedEnv $envFile
  Write-Host "Ayarlar $savedEnv dosyasından geri alındı."
}
if (Test-Path $envFile) {
  $lines = [string[]](Get-Content -Encoding UTF8 $envFile)
} else {
  $newInstall = $true
  $d = $DataDir -replace "\\", "/"
  $lines = [string[]]@(
    "# Parça Takip ERP (Docker'sız) ayarları. Değişiklikten sonra: KURULUM_DOCKERSIZ.bat",
    "ERP_DATABASE_URL=sqlite:///$d/erp.db",
    "ERP_DATA_DIR=$d/data",
    "ERP_BACKUP_DIR=$d/yedek",
    "ERP_JWT_SECRET=$(RandomText 48)",
    "ERP_ADMIN_USER=admin",
    "ERP_ADMIN_PASSWORD=$(RandomText 10)",
    "ERP_BACKUP_TIME=02:00",
    "ERP_BACKUP_KEEP_DAYS=14",
    "ERP_MAX_UPLOAD_MB=2048",
    "ERP_UPDATE_FEED_URL="
  )
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
WriteLines $envFile $lines
Copy-Item $envFile $savedEnv -Force

# ---------- 6. Database ----------
Step "Veritabanı"
Push-Location $backend
try {
  $env:PYTHONUTF8 = "1"
  Run $venvPy @("-m", "app.cli", "migrate") "Veritabanı güncelleme"
} finally { Pop-Location }

# ---------- 7. Start-up task ----------
Step "Açılışta otomatik başlatma ($TaskName görevi)"
$log = Join-Path $DataDir "erp.log"
# PYTHONUTF8: Turkish text in the log must not depend on the Windows code page
$cmdLine = "/c set PYTHONUTF8=1&& set PYTHONUNBUFFERED=1&& `"$venvPy`" -m app.cli serve --port $Port >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdLine -WorkingDirectory $backend
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Description "Parça Takip ERP web sunucusu ve günlük yedek" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$ok = $false
$deadline = (Get-Date).AddMinutes(2)
while (-not $ok -and (Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  try { $ok = ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:$Port/api/health").StatusCode -eq 200) } catch { }
}
if (-not $ok) { Fail "Sunucu açılmadı. Günlük: $log" }

if ($Demo) {
  Step "Demo projeler yükleniyor"
  Push-Location $backend
  try { Run $venvPy @("-m", "app.cli", "seed") "Demo veri" } finally { Pop-Location }
}

# ---------- 8. Firewall ----------
$ruleName = "Parca Takip ERP ($Port)"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}

# ---------- 9. Done ----------
$suffix = ""
if ($Port -ne 80) { $suffix = ":$Port" }
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.InterfaceAlias -notmatch "vEthernet|WSL|Docker|Loopback" } |
       Select-Object -ExpandProperty IPAddress
Write-Host ""
Write-Host "Kurulum tamam (Docker'sız)." -ForegroundColor Green
Write-Host "  Bu bilgisayardan : http://localhost$suffix"
foreach ($ip in $ips) { Write-Host "  Yerel ağdan      : http://$ip$suffix" }
Write-Host "  Veriler          : $DataDir   (günlük: $log)"
if ($newInstall) {
  Write-Host "  Kullanıcı adı    : $(EnvValue $lines 'ERP_ADMIN_USER')"
  Write-Host "  İlk şifre        : $(EnvValue $lines 'ERP_ADMIN_PASSWORD')   (girişten sonra değiştirin)"
}
if (-not $NoBrowser) { Start-Process "http://localhost$suffix" | Out-Null }
