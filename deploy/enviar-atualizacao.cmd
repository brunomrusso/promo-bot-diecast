@echo off
setlocal
rem Envia o bot para o servidor: confere, testa, guarda a versao (deploy\voltar-versao.cmd desfaz) e reinicia.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
tar -czf "%TEMP%\promobot-update.tgz" --exclude=__pycache__ --exclude=*.db --exclude=*.db-* --exclude=core/backups --exclude=.fuse_hidden* core scrapers templates static deploy main.py dashboard.py config.py requirements.txt .gitignore .gitattributes test_site_export.py test_price_engine.py test_site_ranking.py
if errorlevel 1 goto erro
scp -i "%KEY%" "%TEMP%\promobot-update.tgz" deploy\aplicar-atualizacao.sh %SERVER%:~/
if errorlevel 1 goto erro
ssh -t -i "%KEY%" %SERVER% "bash ~/aplicar-atualizacao.sh 'Envio %date% %time:~0,5%'"
if errorlevel 1 (
  echo.
  echo ############################################################
  echo   ATENCAO: a atualizacao NAO foi aplicada. Nada mudou no bot.
  echo   Copie a saida acima e cole no Claude.
  echo ############################################################
  pause
  exit /b 1
)
echo.
echo ATUALIZACAO APLICADA.
call "%~dp0salvar-no-github.cmd" "Envio do bot %date% %time:~0,5%" nopause
echo Copie toda a saida acima e cole no Claude.
pause
exit /b
:erro
echo Falhou antes de aplicar. Copie a saida acima e cole no Claude.
pause
