@echo off
setlocal
rem Liga a Lomadee de novo no bot.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\lomadee.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/lomadee.sh ligar"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
