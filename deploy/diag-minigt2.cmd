@echo off
setlocal
rem Diagnostico da Mini GT pela API do ML (nao muda nada, nao usa proxy).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\diag-minigt2.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-minigt2.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
