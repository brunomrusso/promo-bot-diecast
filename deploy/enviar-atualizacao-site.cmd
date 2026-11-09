@echo off
setlocal
rem Envia a atualizacao "achadinhos no site" para a VM da Oracle e aplica.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
findstr /b "SITE_" .env > "%TEMP%\site.env"
tar -czf "%TEMP%\promobot-update.tgz" core/db.py core/site_export.py config.py main.py dashboard.py templates/monitored.html scrapers/mercadolivre.py scrapers/__init__.py test_site_export.py .env.example deploy/scripts/aplicar-atualizacao-site.sh
if errorlevel 1 goto erro
scp -i "%KEY%" "%TEMP%\promobot-update.tgz" "%TEMP%\site.env" %SERVER%:~/
set "SCPERR=%ERRORLEVEL%"
del "%TEMP%\site.env"
if not "%SCPERR%"=="0" goto erro
ssh -t -i "%KEY%" %SERVER% "cd /home/ubuntu/promo-bot-carros && tar xzf ~/promobot-update.tgz deploy/scripts/aplicar-atualizacao-site.sh && bash deploy/scripts/aplicar-atualizacao-site.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
exit /b
:erro
echo Falhou antes de aplicar. Copie a saida acima e cole no Claude.
pause
