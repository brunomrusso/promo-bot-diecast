@echo off
setlocal
rem Envia o ML_PROXY_URL do .env deste computador para a VM, testa e reinicia o bot.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
cd /d "%~dp0.."
findstr /b "ML_PROXY_URL=" .env > "%TEMP%\proxy.env"
scp -i "%KEY%" "%TEMP%\proxy.env" deploy\aplicar-proxy-ml.sh %SERVER%:~/
set "SCPERR=%ERRORLEVEL%"
del "%TEMP%\proxy.env"
if not "%SCPERR%"=="0" goto erro
ssh -t -i "%KEY%" %SERVER% "bash ~/aplicar-proxy-ml.sh"
echo.
echo Copie toda a saida acima e cole no Claude.
pause
exit /b
:erro
echo Falhou ao enviar. Copie a saida acima e cole no Claude.
pause
