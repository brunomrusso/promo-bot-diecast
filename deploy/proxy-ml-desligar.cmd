@echo off
setlocal
rem Desliga o proxy do Mercado Livre (o Chrome do ML passa a usar o IP da VPS).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\proxy-ml.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/proxy-ml.sh desligar"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
