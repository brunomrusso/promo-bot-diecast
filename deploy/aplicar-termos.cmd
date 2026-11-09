@echo off
setlocal
rem Simplifica os termos obrigatorios das minis (guarda os antigos antes).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\aplicar-termos.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/aplicar-termos.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
