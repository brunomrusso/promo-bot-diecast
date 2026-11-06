@echo off
setlocal
rem Liga de novo o proxy do Mercado Livre.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\proxy-ml.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/proxy-ml.sh ligar"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
