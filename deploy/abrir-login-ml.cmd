@echo off
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-10-13.key"
set "SERVER=ubuntu@163.176.178.217"
start "Login Mercado Livre" powershell.exe -NoExit -Command "ssh -t -i '%KEY%' -L 5901:localhost:5900 %SERVER% 'bash /home/ubuntu/promo-bot-carros/deploy/ml-login.sh'"
timeout /t 8 /nobreak >nul
if exist "C:\Program Files\TightVNC\tvnviewer.exe" start "" "C:\Program Files\TightVNC\tvnviewer.exe" localhost::5901
if exist "C:\Program Files (x86)\TightVNC\tvnviewer.exe" start "" "C:\Program Files (x86)\TightVNC\tvnviewer.exe" localhost::5901
