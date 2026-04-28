@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    python -m venv "%ROOT%.venv"
    if errorlevel 1 goto error
)

"%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 goto error

call :check_update

"%PYTHON%" -m doc_anonymizer.app.main
if errorlevel 1 goto error

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
echo.
echo DocAnonymous konnte nicht gestartet werden.
pause
exit /b 1
