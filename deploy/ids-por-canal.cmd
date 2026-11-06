@echo off
setlocal
rem IDs por canal: Amazon russowhats-20/russosite-20 e Mercado Livre russowhats/russosite (bot/site).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\ids-por-canal.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/ids-por-canal.sh russowhats-20 russosite-20 russowhats russosite"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
