@echo off
rem Fecha as portas 80/443 da VPS para tudo que nao for a Cloudflare (SSH continua igual).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
scp -q -i "%KEY%" deploy\firewall-cloudflare.sh %SERVER%:~/
ssh -i "%KEY%" %SERVER% "bash ~/firewall-cloudflare.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
