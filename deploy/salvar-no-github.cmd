@echo off
setlocal EnableExtensions
rem Salva no GitHub a versao atual do bot e do site (historico para desfazer qualquer mudanca).
rem Uso: salvar-no-github.cmd ["descricao"] [nopause]
where git >nul 2>nul || (echo Git nao esta instalado. Instale em https://git-scm.com/download/win e rode de novo. & if not "%~2"=="nopause" pause & exit /b 1)
set "MSG=%~1"
if "%MSG%"=="" set /p "MSG=Descreva a mudanca (Enter = atualizacao): "
if "%MSG%"=="" set "MSG=atualizacao"
set "ID="
for /f "delims=" %%e in ('git config --global user.email 2^>nul') do set "ID=1"
if not defined ID set "GITID=-c user.name=Bruno -c user.email=runbrunorun2@gmail.com"
set "FALHA="
call :repo "%~dp0.." "https://github.com/brunomrusso/promo-bot-diecast.git" master BOT
call :repo "%~dp0..\..\russo-diecast-site" "https://github.com/brunomrusso/russo-diecast-site.git" main SITE
echo.
if defined FALHA (echo ATENCAO: algo nao foi salvo no GitHub. Copie a saida acima e cole no Claude.) else (echo SALVO NO GITHUB.)
if not "%~2"=="nopause" pause
exit /b
:repo
echo.
echo == %~4
pushd "%~1" || (set "FALHA=1" & exit /b)
if not exist .git (git init -q & git branch -M %~3 & git remote add origin %~2)
git add -A
git diff --cached --name-only | findstr /r /i /c:"^\.env$" /c:"config-amazon\.php" /c:"deals\.db" >nul
if not errorlevel 1 (echo PERIGO: arquivo secreto ou banco de dados ia junto. Nada foi salvo. & git reset -q & set "FALHA=1" & popd & exit /b)
git diff --cached --quiet
if errorlevel 1 (git %GITID% commit -q -m "%MSG%" && echo    commit: %MSG%) else (echo    nada novo para salvar)
git ls-remote --exit-code --heads origin %~3 >nul 2>nul
if not errorlevel 1 git %GITID% pull -q --rebase origin %~3
git push -q -u origin %~3 || set "FALHA=1"
if not defined FALHA echo    enviado para o GitHub
popd
exit /b
