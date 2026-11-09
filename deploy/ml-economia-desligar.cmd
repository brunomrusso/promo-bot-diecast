@echo off
setlocal
rem Desliga o bloqueio de imagens no Chrome do ML (economia de proxy).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\ml-economia.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/ml-economia.sh desligar"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
