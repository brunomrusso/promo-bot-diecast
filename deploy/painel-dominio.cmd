@echo off
rem Liga o painel em https://painel.russodiecast.online (precisa do registro DNS "painel" criado antes).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\painel-dominio.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/painel-dominio.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
