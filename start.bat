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

"%PYTHON%" -m doc_anonymizer.app.main
if errorlevel 1 goto error

exit /b 0

:error
echo.
echo DocAnonymous konnte nicht gestartet werden.
pause
exit /b 1
