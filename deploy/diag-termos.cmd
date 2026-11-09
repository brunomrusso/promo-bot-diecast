@echo off
setlocal
rem Minis com termos obrigatorios demais e sugestao (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\diag-termos.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-termos.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
