@echo off
setlocal
cd /d "%~dp0"

echo.
echo  AKTA chromatography figure builder
echo  ----------------------------------
echo.

set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
  )
)
if not defined PY goto :nopython

if not exist ".venv\Scripts\python.exe" (
  echo  Creating a private environment in .venv ...
  %PY% -m venv .venv >nul 2>nul
)

if exist ".venv\Scripts\python.exe" (
  set "RUNPY=.venv\Scripts\python.exe"
) else (
  echo  Could not create .venv, using the system Python instead.
  set "RUNPY=%PY%"
)

"%RUNPY%" -c "import matplotlib, pandas" >nul 2>nul
if not errorlevel 1 goto :run

if exist "wheels\" (
  echo  Installing the bundled packages from wheels\ ...
  "%RUNPY%" -m pip install --no-index --find-links wheels -r requirements.txt
) else (
  echo  Installing matplotlib and pandas ...
  "%RUNPY%" -m pip install -r requirements.txt
)
if errorlevel 1 goto :failed

:run
echo  Starting the web interface ...
echo.
"%RUNPY%" webapp.py --open
exit /b 0

:nopython
echo  Python 3.9 or newer was not found.
echo  Install it from https://www.python.org/downloads/ and tick
echo  "Add python.exe to PATH", then run this file again.
echo.
pause
exit /b 1

:failed
echo.
echo  Setup failed. If this machine has no internet access, put the wheel
echo  files for matplotlib, pandas and their dependencies in wheels\ and run
echo  this file again.
echo.
pause
exit /b 1
