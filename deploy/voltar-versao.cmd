@echo off
setlocal
rem Volta o bot do servidor para uma versao anterior (mostra a lista e pergunta qual).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\voltar-versao.sh %SERVER%:~/
ssh -t -i "%KEY%" %SERVER% "bash ~/voltar-versao.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
