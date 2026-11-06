@echo off
setlocal
rem Testa a API oficial do Mercado Livre para o ranking de mais vendidos (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\diag-ml-api2.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-ml-api2.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
