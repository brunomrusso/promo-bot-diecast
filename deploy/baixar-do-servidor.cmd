@echo off
rem Copia do servidor para a pasta "Claude outputs" os arquivos que o Claude precisa comparar (so leitura no servidor).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
if not exist "Claude outputs" mkdir "Claude outputs"
scp -i "%KEY%" %SERVER%:/home/ubuntu/promo-bot-carros/core/manual_jobs.py "Claude outputs\manual_jobs.servidor.py"
echo.
echo Pronto. Avise o Claude.
pause
