@echo off
title Currency Strength Dashboard
echo.
echo  ====================================================
echo    Currency Strength Indicator
echo  ====================================================
echo.

cd /d "C:\CurrencyStrength"

echo  [1] Avvio scheduler orari in background...
start /B "" "C:\CurrencyStrength\.venv\Scripts\pythonw.exe" "C:\CurrencyStrength\scheduler.py"
echo  [OK] Scheduler avviato.
echo.

echo  [2] Avvio dashboard...
echo.

"C:\CurrencyStrength\.venv\Scripts\streamlit.exe" run "C:\CurrencyStrength\app.py" --server.headless true --browser.gatherUsageStats false

echo.
echo  Dashboard terminata.

:: Ferma lo scheduler
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq Currency*" >nul 2>&1

pause
