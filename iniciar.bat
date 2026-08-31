@echo off
REM ===================================================================
REM  Formula Magica B3 - inicializador para Windows
REM  De duplo clique neste arquivo. Na primeira vez ele instala tudo.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Formula Magica B3

echo.
echo  ============================================
echo    FORMULA MAGICA B3
echo  ============================================
echo.

REM --- procura o Python -----------------------------------------------
set PY=
where py >nul 2>&1 && set PY=py -3
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )

if "%PY%"=="" (
  echo  [ERRO] Python nao encontrado.
  echo.
  echo  Baixe em https://www.python.org/downloads/
  echo  IMPORTANTE: na tela de instalacao, marque a caixinha
  echo  "Add Python to PATH" antes de clicar em Install.
  echo.
  pause
  exit /b 1
)

REM --- cria o ambiente virtual na primeira execucao --------------------
if not exist ".venv\Scripts\python.exe" (
  echo  Primeira execucao: preparando o ambiente...
  echo  Isso leva alguns minutos. Nao feche esta janela.
  echo.
  %PY% -m venv .venv
  if errorlevel 1 goto erro
  call .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
  call .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto erro
  echo.
  echo  Ambiente pronto.
  echo.
)

REM --- verifica as fontes de dados na primeira vez ---------------------
if not exist ".venv\verificado.txt" (
  echo  Verificando as fontes de dados ^(CVM, B3, Yahoo^)...
  echo.
  call .venv\Scripts\python.exe verificar_dados.py
  echo. > .venv\verificado.txt
  echo.
  echo  Pressione qualquer tecla para abrir a plataforma...
  pause >nul
)

echo.
echo  Abrindo no navegador. Para encerrar, feche esta janela
echo  ou pressione Ctrl+C.
echo.
call .venv\Scripts\python.exe -m streamlit run app.py
goto fim

:erro
echo.
echo  [ERRO] A instalacao falhou. Copie a mensagem acima.
echo.
pause
exit /b 1

:fim
pause
