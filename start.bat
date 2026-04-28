@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "SPLASH_SCRIPT=%ROOT%scripts\splash_screen.ps1"
set "SPLASH_IMAGE=%ROOT%doc_anonymizer\app\assets\splash.png"
set "SPLASH_SIGNAL=%TEMP%\DocAnonymousSplash_%RANDOM%%RANDOM%.done"

call :start_splash

if not exist "%PYTHON%" (
    python -m venv "%ROOT%.venv"
    if errorlevel 1 goto error
)

"%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 goto error

call :check_update

call :stop_splash
set "DOCANONYMIZER_EXTERNAL_SPLASH=1"
"%PYTHON%" -m doc_anonymizer.app.main
if errorlevel 1 goto error

exit /b 0

:start_splash
if exist "%SPLASH_SCRIPT%" if exist "%SPLASH_IMAGE%" (
    if exist "%SPLASH_SIGNAL%" del "%SPLASH_SIGNAL%" >nul 2>nul
    start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%SPLASH_SCRIPT%" -ImagePath "%SPLASH_IMAGE%" -SignalFile "%SPLASH_SIGNAL%" -MinimumMilliseconds 3000
)
exit /b 0

:stop_splash
type nul > "%SPLASH_SIGNAL%"
exit /b 0

:check_update
where git >nul 2>nul
if errorlevel 1 (
    echo Git nicht gefunden, Update-Pruefung uebersprungen.
    exit /b 0
)

pushd "%ROOT%" >nul
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo Kein Git-Repository, Update-Pruefung uebersprungen.
    popd >nul
    exit /b 0
)

git fetch --quiet
if errorlevel 1 (
    echo GitHub-Update-Pruefung fehlgeschlagen.
    popd >nul
    exit /b 0
)

git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >nul 2>nul
if errorlevel 1 (
    echo Kein Git-Upstream konfiguriert, Update-Pruefung uebersprungen.
    popd >nul
    exit /b 0
)

for /f "delims=" %%i in ('git rev-parse HEAD') do set "LOCAL=%%i"
for /f "delims=" %%i in ('git rev-parse "@{u}"') do set "REMOTE=%%i"
for /f "delims=" %%i in ('git merge-base HEAD "@{u}"') do set "BASE=%%i"
for /f "delims=" %%i in ('git rev-parse --abbrev-ref --symbolic-full-name "@{u}"') do set "UPSTREAM=%%i"

if "%LOCAL%"=="%REMOTE%" (
    echo DocAnonymous ist auf dem neuesten Stand.
) else if "%LOCAL%"=="%BASE%" (
    echo Update verfuegbar: %UPSTREAM% enthaelt neue Versionen. Zum Aktualisieren: git pull --ff-only
) else if "%REMOTE%"=="%BASE%" (
    echo Lokale Version ist neuer als GitHub.
) else (
    echo Lokale und GitHub-Version sind auseinander gelaufen. Bitte manuell pruefen.
)

popd >nul
exit /b 0

:error
call :stop_splash
echo.
echo DocAnonymous konnte nicht gestartet werden.
pause
exit /b 1
