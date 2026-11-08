@echo off
REM EDAPGui Startup Script
REM On first run: creates a Python virtual environment (venv folder) and installs the requirements.
REM After that: just starts EDAPGui.
REM
REM Fork RP2: rewritten. Three problems with the original:
REM  1. Nearly all of it ran inside one big "if not exist ... ( ... )" block. Inside a block, cmd.exe reads
REM     %errorlevel% once, when the block starts, so the Python version checks and the "did pip fail?"
REM     check never saw real results. It always tried "py -3.11", and a failed install still reported
REM     success and launched.
REM  2. Setup counted as done once venv\Scripts\python.exe existed, so after a failed install every later
REM     run skipped setup and launched a broken environment. Now a marker file is written only after the
REM     requirements install successfully.
REM  3. It offered Python 3.9 and 3.10, which can't install the pinned requirements (pandas, scipy,
REM     contourpy and networkx are 3.11+ only). Supported now: 3.11, 3.12, 3.13 (3.11 preferred). 3.14 is
REM     not supported yet because PaddlePaddle has no 3.14 build.
REM Flat structure, no big blocks, so errorlevel is always current.
REM
REM Every exit code check is "if %errorlevel% neq 0", not "if errorlevel 1". "if errorlevel 1" means "1 or
REM more", so it misses negative codes: the newer py.exe launcher exits with one (0xA000000x) when the
REM requested version isn't installed, and so does a crash (0xC000000x). Safe here because no check is
REM inside a ( ) block.

REM Keeps PYTHON_CMD and MARKER out of the console this was started from.
setlocal
cd /d "%~dp0"

set "MARKER=venv\edap_setup_complete.txt"
if exist "%MARKER%" goto run

REM An existing venv on a supported Python (e.g. from before this script was updated) is reused: pip is
REM simply run again, which takes seconds if everything is already installed and finishes a partial install.
set "PYTHON_CMD="
if exist "venv\Scripts\python.exe" call :try_venv
if defined PYTHON_CMD goto install

REM ---- Find a supported Python, preferring 3.11 ----
call :try_python py -3.11
if not defined PYTHON_CMD call :try_python py -3.12
if not defined PYTHON_CMD call :try_python py -3.13
if not defined PYTHON_CMD call :try_python py
if not defined PYTHON_CMD call :try_python python
if defined PYTHON_CMD goto setup

echo.
echo Error: EDAPGui needs Python 3.11, 3.12 or 3.13. Python 3.11.9 is recommended:
echo   https://www.python.org/downloads/release/python-3119/
echo Python 3.9 and 3.10 can't install the required packages, and 3.14 isn't supported yet.
echo When installing, tick "Add Python to PATH".
pause
exit /b 1

:setup
echo Using %PYTHON_CMD%
echo Creating Python virtual environment...
echo This may take a moment, please wait...
REM --clear: any venv still here is on an unsupported Python or broken (see :try_venv), so start fresh.
%PYTHON_CMD% -m venv --clear venv
if %errorlevel% neq 0 goto venv_failed
if not exist "venv\Scripts\python.exe" goto venv_failed

:install
echo Installing requirements. This can take several minutes...
REM A failed pip upgrade isn't fatal; the existing pip can still install the requirements.
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt
if %errorlevel% neq 0 goto install_failed

REM Redirect first: "py -3.12> file" would read the trailing 2 as "redirect stderr".
> "%MARKER%" echo Setup completed with %PYTHON_CMD%
echo Virtual environment setup complete!

:run
REM Run EDAPGui with venv python
echo Starting EDAPGui...
venv\Scripts\python.exe EDAPGui.py
exit /b %errorlevel%

:venv_failed
echo Error: Failed to create the virtual environment.
echo If EDAPGui is running, close it and try again. Otherwise delete the venv folder and try again.
pause
exit /b 1

:install_failed
echo.
echo Error: Failed to install the requirements. See the messages above.
echo Run start_ed_ap.bat again to retry once the problem is fixed.
pause
exit /b 1

REM ---- Sets PYTHON_CMD to the existing venv if it is on Python 3.11 to 3.13 and its pip works ----
REM Without the pip check, a venv whose pip never got installed would be reused, and fail, on every run.
:try_venv
call :try_python venv\Scripts\python.exe
if not defined PYTHON_CMD exit /b 0
venv\Scripts\python.exe -m pip --version >nul 2>&1
if %errorlevel% neq 0 set "PYTHON_CMD="
exit /b 0

REM ---- Sets PYTHON_CMD to the given command if it runs Python 3.11 to 3.13 ----
:try_python
%* -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if %errorlevel% neq 0 exit /b 0
set "PYTHON_CMD=%*"
exit /b 0
