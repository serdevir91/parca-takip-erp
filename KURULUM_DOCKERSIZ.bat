@echo off
rem Parca Takip ERP - Dockersiz Windows kurulum / guncelleme. Cift tiklayin.
rem Python 3.12 + Node.js kurar (yoksa), uygulamayi Windows acilisinda baslayan gorev olarak kaydeder.
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows_native_install.ps1" %*
echo.
pause
