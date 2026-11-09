@echo off
setlocal
rem Publica no russodiecast.com.br os arquivos do SITE listados abaixo (pasta russo-diecast-site\site), via FTP do bot.
rem products.json e achadinhos.json NAO vao daqui: quem cuida deles e o bot (ranking do site) e a tarefa diaria.
set "KEY=C:\Users\bruno\Downloads\ssh-key-2026-11-05.key"
set "SERVER=ubuntu@187.41.122.7"
set "SITE=%~dp0..\..\russo-diecast-site\site"
set "ARQUIVOS=index.html sobre.html privacidade.html site.webmanifest assets/js/app.js assets/js/consent.js assets/css/style.css assets/img/og-image.jpg assets/img/logo.png assets/img/logo.webp assets/img/favicon.ico assets/img/icon-32.png assets/img/icon-180.png assets/img/icon-192.png assets/img/icon-512.png"
cd /d "%SITE%" || goto erro
tar -czf "%TEMP%\site-upload.tgz" %ARQUIVOS%
if errorlevel 1 goto erro
cd /d "%~dp0.."
scp -q -i "%KEY%" "%TEMP%\site-upload.tgz" deploy\scripts\publicar-site.sh %SERVER%:~/
if errorlevel 1 goto erro
ssh -i "%KEY%" %SERVER% "bash ~/publicar-site.sh"
if errorlevel 1 goto erro
call "%~dp0salvar-no-github.cmd" "Site publicado %date% %time:~0,5%" nopause
echo.
echo Copie toda a saida acima e cole no Claude.
pause
exit /b
:erro
echo Falhou. Copie a saida acima e cole no Claude.
pause
