@echo off
setlocal
rem Por que o Pesquisar das minis nao traz resultado (nao muda nada).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\scripts\diag-pesquisa.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/diag-pesquisa.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
