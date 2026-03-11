@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM  Build APK with background execution permissions
REM ═══════════════════════════════════════════════════════════════════════
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

flet build apk ^
  --android-permissions ^
    android.permission.INTERNET=True ^
    android.permission.WAKE_LOCK=True ^
    android.permission.FOREGROUND_SERVICE=True ^
    android.permission.FOREGROUND_SERVICE_DATA_SYNC=True ^
    android.permission.POST_NOTIFICATIONS=True ^
    android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS=True ^
    android.permission.RECEIVE_BOOT_COMPLETED=True ^
  --product "Currency Strength" ^
  --description "Forex currency strength monitor with Telegram alerts"

echo.
echo Done! APK is in build\apk\
pause
