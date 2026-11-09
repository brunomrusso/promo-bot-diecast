@echo off
setlocal
rem Grava o link do site do McQueen Rusteze gerado a mao (nao usa proxy).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\gravar-link-mcqueen.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/gravar-link-mcqueen.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
