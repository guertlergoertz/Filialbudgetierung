@echo off
chcp 65001 >nul
echo --------------------------------------------------
echo Lade Code fuer revenue_planner aus GitHub...
echo --------------------------------------------------

set "BENUTZER=guertlergoertz"
set "REPO=Filialbudgetierung"
set "BRANCH=main"

:: %~dp0 = Ordner dieser Batch-Datei (mit abschliessendem \)
set "ZIEL=%~dp0"

echo Downloade ZIP von GitHub...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/%BENUTZER%/%REPO%/archive/refs/heads/%BRANCH%.zip' -OutFile '%ZIEL%temp.zip'"

echo Entpacke...
powershell -Command "Expand-Archive -Path '%ZIEL%temp.zip' -DestinationPath '%ZIEL%temp_entpackt' -Force"

echo Kopiere Dateien...
xcopy "%ZIEL%temp_entpackt\%REPO%-%BRANCH%\Allgemein-master\revenue_planner\*" "%ZIEL%" /E /Y /Q >nul

echo Raeume auf...
rmdir /S /Q "%ZIEL%temp_entpackt"
del "%ZIEL%temp.zip"

echo --------------------------------------------------
echo Fertig! Starte das Programm mit start.bat
echo --------------------------------------------------
pause