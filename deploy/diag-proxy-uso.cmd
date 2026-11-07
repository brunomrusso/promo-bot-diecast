@echo off
setlocal
rem Mostra o que usou o proxy nas ultimas 24 h (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\diag-proxy-uso.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-proxy-uso.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
