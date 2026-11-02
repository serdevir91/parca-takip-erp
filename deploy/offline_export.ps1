# Run on a Windows machine WITH internet (Docker Desktop): build the images and save
# everything for an offline install into dist-offline\.
#   powershell -ExecutionPolicy Bypass -File deploy\offline_export.ps1 [-Tag 1.0.0]
param([string]$Tag = $(if ($env:ERP_TAG) { $env:ERP_TAG } else { "latest" }))
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Prefix = if ($env:ERP_IMAGE_PREFIX) { $env:ERP_IMAGE_PREFIX } else { "parca-takip" }
$Out = "dist-offline"
$env:ERP_TAG = $Tag
$env:ERP_IMAGE_PREFIX = $Prefix

function Invoke-Checked { param([string]$Cmd, [string[]]$CmdArgs)
  & $Cmd @CmdArgs
  if ($LASTEXITCODE -ne 0) { throw "$Cmd $($CmdArgs -join ' ') başarısız ($LASTEXITCODE)" }
}

Write-Host "İmajlar hazırlanıyor (etiket: $Tag)..."
Invoke-Checked docker @("compose", "build", "--pull")
Invoke-Checked docker @("pull", "postgres:16-alpine")

New-Item -ItemType Directory -Force -Path $Out, "$Out\deploy" | Out-Null
$Tar = "$Out\parca-takip-images-$Tag.tar"
Invoke-Checked docker @("save", "-o", $Tar, "$Prefix-backend:$Tag", "$Prefix-frontend:$Tag", "postgres:16-alpine")

Copy-Item docker-compose.yml, .env.example, README.md $Out -Force
Copy-Item deploy\*.sh, deploy\*.ps1 "$Out\deploy" -Force
$hash = (Get-FileHash -Algorithm SHA256 $Tar).Hash.ToLower()
"$hash  parca-takip-images-$Tag.tar" | Set-Content -Encoding ascii "$Tar.sha256"

$mb = [math]::Round((Get-Item $Tar).Length / 1MB)
Write-Host "Hazır: $Out\ ($mb MB). Bu klasörü sunucuya kopyalayıp deploy\offline_import.ps1 çalıştırın."
