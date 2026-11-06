@echo off
setlocal
rem Mostra o que esta gastando o proxy do Mercado Livre (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\diag-proxy.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-proxy.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
