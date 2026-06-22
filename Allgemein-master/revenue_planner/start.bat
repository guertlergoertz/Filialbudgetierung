@echo off
chcp 65001 >nul
title Filialumsatzplanung

echo ============================================
echo   Filialumsatzplanung wird gestartet...
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden.
    echo Bitte Python installieren: https://python.org/downloads
    echo Wichtig: "Add Python to PATH" anhaeken!
    pause
    exit /b 1
)

:: Create virtual environment if not exists
if not exist ".venv" (
    echo Erstelle Umgebung (einmalig, ca. 1 Minute^)...
    python -m venv .venv
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Install / update dependencies
echo Pruefe Abhaengigkeiten...
pip install -q -r requirements.txt

:: Start app
echo.
echo ============================================
echo   App startet - Browser oeffnet sich gleich
echo   Zum Beenden: dieses Fenster schliessen
echo ============================================
echo.

streamlit run app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false

pause
