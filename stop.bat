@echo off
echo Attempting to stop the background translator script (pythonw.exe)...
echo.

REM This command forcefully stops ALL background python processes.
REM It is more reliable because it does not depend on a window title.
taskkill /F /IM pythonw.exe

echo.
echo If the script was running in the background, it has been stopped.
pause