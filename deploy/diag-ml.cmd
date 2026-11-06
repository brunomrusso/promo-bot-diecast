@echo off
setlocal
rem Mostra como o Chrome do ML do bot esta configurado e o que fez (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\diag-ml.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-ml.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
