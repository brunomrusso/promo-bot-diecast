@echo off
rem Diagnostico: minis dentro do alvo que nao viraram oportunidade.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\diag-alvos.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-alvos.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
