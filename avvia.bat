@echo off
:: ============================================
::  Currency Strength Indicator - Avvio Rapido
:: ============================================
title Currency Strength Dashboard
cd /d "%~dp0"

echo.
echo  ====================================================
echo    Currency Strength Indicator - Avvio
echo  ====================================================
echo.
echo  Directory: %cd%
echo.

:: Verifica che il file ps1 esista
if not exist "%~dp0setup_and_run.ps1" (
    echo  ERRORE: setup_and_run.ps1 non trovato in %~dp0
    echo.
    pause
    exit /b 1
)

:: Avvia lo script PowerShell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& {Set-Location '%~dp0'; & '%~dp0setup_and_run.ps1'}"

echo.
echo  ====================================================
echo  Dashboard terminata. Premi un tasto per chiudere.
echo  ====================================================
pause
