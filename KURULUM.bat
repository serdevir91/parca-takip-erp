@echo off
rem Parca Takip ERP - Windows kurulum / guncelleme. Cift tiklayin.
rem Guvenlik duvari kurali icin yonetici izni ister.
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath %~f0"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows_install.ps1" %*
echo.
pause
