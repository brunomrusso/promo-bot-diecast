@echo off
setlocal
rem Lista os achadinhos do ML sem link do site (nao muda nada, nao usa proxy).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\diag-links-site.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-links-site.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
