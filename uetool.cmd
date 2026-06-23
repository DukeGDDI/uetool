@echo off
rem uetool launcher (Windows). Works from cmd.exe and PowerShell.
rem Add this folder to your PATH. Set UETOOL_PYTHON if `python` is older than 3.11.
setlocal
if defined UETOOL_PYTHON (set "PY=%UETOOL_PYTHON%") else (set "PY=python")
"%PY%" "%~dp0uetool.py" %*
exit /b %ERRORLEVEL%
