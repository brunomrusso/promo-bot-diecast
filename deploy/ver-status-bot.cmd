@echo off
rem Mostra um resumo do bot na VM (log, lojas, sessao do ML, envio ao site).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\status-bot.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/status-bot.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
