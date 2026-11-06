@echo off
rem Volta o bot para a VM Oracle antiga (para a VPS nova e religa a antiga).
set "OLDKEY=C:\Users\bruno\Downloads\ssh-key-2026-10-13.key"
set "OLD=ubuntu@163.176.23.249"
set "NEWKEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
ssh -i "%NEWKEY%" ubuntu@187.41.122.7 "sudo systemctl disable --now promobot dashboard dashboard-tunnel promobot-backup.timer"
ssh -i "%OLDKEY%" %OLD% "sudo systemctl enable --now promobot dashboard dashboard-tunnel promobot-backup.timer && systemctl is-active promobot dashboard"
echo.
echo Copie a saida acima e cole no Claude.
pause
