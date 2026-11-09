@echo off
setlocal
rem Desliga a Lomadee em todo o bot (o token fica guardado).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\lomadee.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/lomadee.sh desligar"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
