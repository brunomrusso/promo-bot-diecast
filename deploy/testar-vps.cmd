@echo off
rem Testa o acesso SSH a VPS nova da Hostinger (so leitura, nao muda nada).
rem Experimenta cada chave ssh-key-*.key da pasta Downloads e mostra qual funciona.
set "SERVER=root@187.41.122.7"
for %%K in ("C:\Users\bruno\Downloads\ssh-key-*.key") do (
  echo.
  echo == testando %%~nxK
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "%%~K" %SERVER% "echo CONECTOU; hostname; lsb_release -ds; echo CPUs: $(nproc); free -h | head -2; df -h / | tail -1; echo -n 'Pais do IP: '; curl -s https://ipinfo.io/country; echo; python3 --version" && echo ^>^>^> CHAVE QUE FUNCIONA: %%~nxK
)
echo.
echo Copie toda a saida acima e cole no Claude.
pause
