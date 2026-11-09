@echo off
rem Diagnostico: desempenho do bot na VPS (so leitura).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\diag-desempenho.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-desempenho.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
