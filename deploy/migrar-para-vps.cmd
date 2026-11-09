@echo off
setlocal
rem Migra o bot da VM Oracle (antiga) para a VPS Hostinger (nova).
rem A VM antiga so e PARADA (nao apagada). Para voltar: deploy\voltar-vm-antiga.cmd
set "OLDKEY=C:\Users\bruno\Downloads\ssh-key-2026-10-13.key"
set "OLD=ubuntu@163.176.23.249"
set "NEWKEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "NEWIP=187.41.122.7"
cd /d "%~dp0.."
echo ===== PASSO 1: preparando a VPS nova (usuario, pacotes, Chrome)
scp -i "%NEWKEY%" deploy\scripts\migrar-vps-1-root.sh root@%NEWIP%:/root/
if errorlevel 1 goto erro
ssh -i "%NEWKEY%" root@%NEWIP% "bash /root/migrar-vps-1-root.sh"
if errorlevel 1 goto erro
echo ===== PASSO 2: parando o bot na VM antiga e empacotando (banco, .env, sessao do ML)
ssh -i "%OLDKEY%" %OLD% "sudo systemctl stop promobot dashboard dashboard-tunnel && cd /home/ubuntu && tar czf /tmp/promobot-migr.tgz --exclude=promo-bot-carros/venv --exclude=__pycache__ --exclude=Cache --exclude='Code Cache' --exclude=GPUCache --exclude=CacheStorage promo-bot-carros && ls -lh /tmp/promobot-migr.tgz"
if errorlevel 1 goto erro_antiga
echo ===== PASSO 3: copiando para a VPS nova (passa pelo seu PC)
scp -i "%OLDKEY%" %OLD%:/tmp/promobot-migr.tgz "%TEMP%\promobot-migr.tgz"
if errorlevel 1 goto erro_antiga
scp -i "%NEWKEY%" "%TEMP%\promobot-migr.tgz" ubuntu@%NEWIP%:/home/ubuntu/
if errorlevel 1 goto erro_antiga
scp -i "%NEWKEY%" deploy\scripts\migrar-vps-2-ubuntu.sh ubuntu@%NEWIP%:/home/ubuntu/
if errorlevel 1 goto erro_antiga
echo ===== PASSO 4: instalando e ligando o bot na VPS nova (5-10 min)
ssh -i "%NEWKEY%" ubuntu@%NEWIP% "tar xzf ~/promobot-migr.tgz -C ~ && bash ~/migrar-vps-2-ubuntu.sh"
if errorlevel 1 goto erro_antiga
echo ===== PASSO 5: desativando o inicio automatico na VM antiga (ela fica parada, nada e apagado)
ssh -i "%OLDKEY%" %OLD% "sudo systemctl disable promobot dashboard dashboard-tunnel promobot-backup.timer"
del "%TEMP%\promobot-migr.tgz" 2>nul
echo.
echo ===== MIGRACAO CONCLUIDA. Copie toda a saida acima e cole no Claude.
pause
exit /b
:erro_antiga
echo.
echo !! Falhou depois de parar o bot antigo. Religando o bot na VM antiga...
ssh -i "%OLDKEY%" %OLD% "sudo systemctl start promobot dashboard dashboard-tunnel"
:erro
echo.
echo !! Migracao interrompida. Copie toda a saida acima e cole no Claude.
pause
exit /b 1
