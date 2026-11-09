@echo off
rem Login manual do Mercado Livre pelo VNC. Pode rodar a qualquer momento.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\ml-login.sh %SERVER%:~/
start "Login Mercado Livre" powershell.exe -NoExit -Command "ssh -t -i '%KEY%' -L 5901:localhost:5900 %SERVER% 'bash ~/ml-login.sh'"
timeout /t 12 /nobreak >nul
if exist "C:\Program Files\TightVNC\tvnviewer.exe" start "" "C:\Program Files\TightVNC\tvnviewer.exe" localhost::5901
if exist "C:\Program Files (x86)\TightVNC\tvnviewer.exe" start "" "C:\Program Files (x86)\TightVNC\tvnviewer.exe" localhost::5901
