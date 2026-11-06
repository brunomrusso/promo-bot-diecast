@echo off
setlocal
rem SO COMPARA o servidor com o seu computador (nao muda nada no bot).
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
tar -czf "%TEMP%\promobot-update.tgz" --exclude=__pycache__ --exclude=*.db --exclude=*.db-* --exclude=core/backups --exclude=.fuse_hidden* core scrapers templates static deploy main.py dashboard.py config.py requirements.txt .gitignore .gitattributes test_site_export.py test_price_engine.py test_site_ranking.py
if errorlevel 1 goto erro
scp -q -i "%KEY%" "%TEMP%\promobot-update.tgz" deploy\comparar-servidor.sh %SERVER%:~/
if errorlevel 1 goto erro
ssh -i "%KEY%" %SERVER% "bash ~/comparar-servidor.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
exit /b
:erro
echo Falhou. Copie a saida acima e cole no Claude.
pause
