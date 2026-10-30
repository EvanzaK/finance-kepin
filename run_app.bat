@echo off
title Hybrid Personal Finance & ShopeeFood Tracker
color 0A
echo ======================================================================
echo    HYBRID PERSONAL FINANCE ^& SHOPEEFOOD DRIVER TRACKER
echo ======================================================================
echo.

:: Cek Python
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=python"
) else (
    if exist "C:\laragon\bin\python\python-3.13\python.exe" (
        set "PY_CMD=C:\laragon\bin\python\python-3.13\python.exe"
    ) else (
        echo [ERROR] Python tidak ditemukan di PATH maupun di C:\laragon\bin\python\python-3.13\python.exe
        pause
        exit /b 1
    )
)

echo [INFO] Menggunakan: %PY_CMD%
echo [INFO] Memeriksa dependensi...
%PY_CMD% -m pip install -q -r requirements.txt

echo.
echo [INFO] Menjalankan server aplikasi...
echo [INFO] Buka browser di: http://127.0.0.1:5000
echo.
%PY_CMD% app.py

pause
