@echo off
setlocal
rem Testa o proxy do Mercado Livre e a conexao direta da VPS (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\proxy-ml.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/proxy-ml.sh testar"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
