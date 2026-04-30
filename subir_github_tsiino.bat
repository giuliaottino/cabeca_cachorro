@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM Script para subir o projeto Quarto/RStudio para o GitHub
REM Uso:
REM   subir_github_tsiino.bat cabeca_cachorro private
REM   subir_github_tsiino.bat cabeca_cachorro public
REM ============================================================

set "REPO_NAME=%~1"
set "VISIBILITY=%~2"
set "BRANCH=main"

if "%REPO_NAME%"=="" set "REPO_NAME=cabeca_cachorro"
if "%VISIBILITY%"=="" set "VISIBILITY=private"

echo ==============================================
echo Subindo projeto para o GitHub
echo Pasta atual: %CD%
echo Repositorio: %REPO_NAME%
echo Visibilidade: %VISIBILITY%
echo Branch: %BRANCH%
echo ==============================================
echo.

REM ------------------------------------------------------------
REM Verificar se esta na raiz do projeto Quarto
REM ------------------------------------------------------------

if not exist "_quarto.yml" (
  echo Erro: nao encontrei _quarto.yml.
  echo Rode este script dentro da pasta raiz do projeto.
  exit /b 1
)

REM ------------------------------------------------------------
REM Verificar dependencias
REM ------------------------------------------------------------

where git >nul 2>nul
if errorlevel 1 (
  echo Erro: git nao esta instalado ou nao esta no PATH.
  exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
  echo Erro: GitHub CLI gh nao esta instalado ou nao esta no PATH.
  echo Instale o GitHub CLI e tente novamente.
  exit /b 1
)

gh auth status >nul 2>nul
if errorlevel 1 (
  echo Voce ainda nao esta autenticada no GitHub CLI.
  echo Rode primeiro:
  echo.
  echo gh auth login
  echo.
  exit /b 1
)

for /f "delims=" %%i in ('gh api user --jq ".login"') do set "GITHUB_USER=%%i"

set "FULL_REPO=%GITHUB_USER%/%REPO_NAME%"
set "REMOTE_URL=https://github.com/%GITHUB_USER%/%REPO_NAME%.git"

echo GitHub autenticado como: %GITHUB_USER%
echo.

REM ------------------------------------------------------------
REM Aviso sobre arquivo ou pasta chamado -p
REM ------------------------------------------------------------

if exist "-p" (
  echo Aviso: existe um arquivo ou pasta chamado "-p".
  echo Se isso foi criado por engano, voce pode remover depois com:
  echo.
  echo del "-p"
  echo.
)

REM ------------------------------------------------------------
REM Criar ou atualizar .gitignore
REM ------------------------------------------------------------

if not exist ".gitignore" type nul > ".gitignore"

findstr /C:"### tsiino Quarto/RStudio ###" ".gitignore" >nul 2>nul

if errorlevel 1 (
  echo.>> ".gitignore"
  echo ### tsiino Quarto/RStudio ###>> ".gitignore"
  echo.>> ".gitignore"
  echo # Historico e sessao do R>> ".gitignore"
  echo .Rhistory>> ".gitignore"
  echo .RData>> ".gitignore"
  echo .Ruserdata>> ".gitignore"
  echo.>> ".gitignore"
  echo # Configuracoes locais do RStudio>> ".gitignore"
  echo .Rproj.user/>> ".gitignore"
  echo.>> ".gitignore"
  echo # Ambiente local com possiveis tokens/senhas>> ".gitignore"
  echo .Renviron>> ".gitignore"
  echo .env>> ".gitignore"
  echo.>> ".gitignore"
  echo # Sistema operacional>> ".gitignore"
  echo .DS_Store>> ".gitignore"
  echo Thumbs.db>> ".gitignore"
  echo.>> ".gitignore"
  echo # Logs e temporarios>> ".gitignore"
  echo *.log>> ".gitignore"
  echo *.tmp>> ".gitignore"
  echo *.temp>> ".gitignore"
  echo *.bak>> ".gitignore"
  echo *.swp>> ".gitignore"
  echo.>> ".gitignore"
  echo # Cache comum>> ".gitignore"
  echo .cache/>> ".gitignore"
  echo __pycache__/>> ".gitignore"
  echo.>> ".gitignore"
  echo # Quarto/R Markdown cache>> ".gitignore"
  echo *_cache/>> ".gitignore"
  echo *_files/>> ".gitignore"
  echo.>> ".gitignore"
  echo # Saidas temporarias do Quarto>> ".gitignore"
  echo .quarto/>> ".gitignore"
  echo.>> ".gitignore"
  echo # Builds de pacote R, caso existam>> ".gitignore"
  echo .Rcheck/>> ".gitignore"
  echo *.tar.gz>> ".gitignore"
  echo *.Rout>> ".gitignore"
  echo.>> ".gitignore"
  echo # NAO ignorar docs/ se voce usa GitHub Pages por /docs>> ".gitignore"
  echo # NAO ignorar _freeze/ se voce usa freeze no Quarto>> ".gitignore"
  echo.>> ".gitignore"
  echo # Dados locais grandes ou sensiveis: descomente manualmente se necessario>> ".gitignore"
  echo # _input_data/>> ".gitignore"
  echo # figures/>> ".gitignore"
)

echo .gitignore criado/atualizado.
echo.

REM ------------------------------------------------------------
REM Renderizar o site Quarto, se quarto estiver instalado
REM ------------------------------------------------------------

where quarto >nul 2>nul
if errorlevel 1 (
  echo Aviso: quarto nao esta disponivel no terminal.
  echo Vou continuar sem renderizar.
) else (
  echo Quarto encontrado. Renderizando o site...
  quarto render
  if errorlevel 1 (
    echo Erro ao renderizar o site com quarto render.
    exit /b 1
  )
  echo Renderizacao concluida.
)

echo.

REM ------------------------------------------------------------
REM Inicializar Git
REM ------------------------------------------------------------

if not exist ".git" (
  echo Inicializando repositorio Git local...
  git init
) else (
  echo Repositorio Git local ja existe.
)

git checkout -B %BRANCH%
git branch -M %BRANCH%

echo.

REM ------------------------------------------------------------
REM Adicionar arquivos e criar commit
REM ------------------------------------------------------------

echo Adicionando arquivos ao Git...
git add -A

echo.
echo Status atual:
git status --short
echo.

git diff --cached --quiet
if errorlevel 1 (
  echo Criando commit...
  git commit -m "Initial commit: add Quarto website"
) else (
  echo Nenhuma alteracao nova para commit.
)

echo.

REM ------------------------------------------------------------
REM Criar repositorio no GitHub
REM ------------------------------------------------------------

gh repo view "%FULL_REPO%" >nul 2>nul
if errorlevel 1 (
  echo Criando repositorio no GitHub...
  gh repo create "%FULL_REPO%" --%VISIBILITY% --description "Website Quarto do projeto tsiino"
  if errorlevel 1 (
    echo Erro ao criar repositorio no GitHub.
    exit /b 1
  )
) else (
  echo O repositorio %FULL_REPO% ja existe no GitHub.
)

echo.

REM ------------------------------------------------------------
REM Configurar remoto origin
REM ------------------------------------------------------------

git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo Configurando remoto origin...
  git remote add origin "%REMOTE_URL%"
) else (
  echo Atualizando remoto origin...
  git remote set-url origin "%REMOTE_URL%"
)

echo.

REM ------------------------------------------------------------
REM Push para GitHub
REM ------------------------------------------------------------

echo Enviando projeto para o GitHub...
git push -u origin %BRANCH%

if errorlevel 1 (
  echo.
  echo Erro ao enviar para o GitHub.
  exit /b 1
)

echo.
echo ==============================================
echo Projeto enviado com sucesso.
echo URL:
echo https://github.com/%FULL_REPO%
echo ==============================================

endlocal