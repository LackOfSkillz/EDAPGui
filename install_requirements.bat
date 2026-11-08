@echo off
REM Quick Requirements Installer for EDAPGui
REM Installs requirements.txt into the best available supported Python (not a venv).
REM Most users should use start_ed_ap.bat instead, which installs into its own venv.
REM
REM Fork RP2: only uses Python 3.11 to 3.13 (3.11 preferred). The original tried 3.10 and 3.9, which can't
REM install the pinned requirements (pandas, scipy, contourpy and networkx are 3.11+ only), and it reported
REM "installation complete" even when pip failed. Now it stops with an error instead.
REM Exit codes are checked with "if %errorlevel% neq 0" because "if errorlevel 1" misses negative codes
REM (see start_ed_ap.bat).

setlocal
cd /d "%~dp0"

echo Installing EDAPGui Requirements...
echo ================================

set "PYTHON_CMD="
call :try_python py -3.11
if not defined PYTHON_CMD call :try_python py -3.12
if not defined PYTHON_CMD call :try_python py -3.13
if not defined PYTHON_CMD call :try_python py
if not defined PYTHON_CMD call :try_python python
if defined PYTHON_CMD goto install

echo Error: EDAPGui needs Python 3.11, 3.12 or 3.13. Python 3.11.9 is recommended:
echo   https://www.python.org/downloads/release/python-3119/
echo Python 3.9 and 3.10 can't install the required packages, and 3.14 isn't supported yet.
pause
exit /b 1

:install
echo Using %PYTHON_CMD%
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 goto install_failed

echo.
echo Requirements installation complete!
echo You can now run: %PYTHON_CMD% EDAPGui.py
echo Or use: start_ed_ap.bat (recommended)
pause
exit /b 0

:install_failed
echo.
echo Error: Failed to install the requirements. See the messages above.
pause
exit /b 1

REM ---- Sets PYTHON_CMD to the given command if it runs Python 3.11 to 3.13 ----
:try_python
%* -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if %errorlevel% neq 0 exit /b 0
set "PYTHON_CMD=%*"
exit /b 0
