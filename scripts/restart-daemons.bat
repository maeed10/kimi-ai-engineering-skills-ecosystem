@echo off
echo Stopping existing Kimi daemons...
taskkill /F /FI "WINDOWTITLE eq policy-engine-server.py*" 2>nul
taskkill /F /FI "WINDOWTITLE eq phase-controller-server.py*" 2>nul
timeout /t 2 /nobreak >nul
start /MIN powershell -WindowStyle Hidden -Command "python "%USERPROFILE%\.kimi\skills\policy-engine\scripts\policy-engine-server.py" --policy-dir "%USERPROFILE%\.kimi\policy" --manifest "%USERPROFILE%\.kimi\policy\manifest.json" --port 9100 --host 127.0.0.1"
start /MIN powershell -WindowStyle Hidden -Command "python "%USERPROFILE%\.kimi\skills\phase-controller\scripts\phase-controller-server.py" --state-dir "%USERPROFILE%\.kimi\state" --port 9101 --host 127.0.0.1"
echo Kimi daemons restarted.
pause
