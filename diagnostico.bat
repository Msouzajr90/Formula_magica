@echo off
REM ===================================================================
REM  Diagnostico dos bancos - descobre em qual conta o Itau, o BTG e o
REM  BMG informam o lucro liquido. So imprime; nao altera nada.
REM  De duplo clique neste arquivo.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Diagnostico dos bancos

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" ( where py >nul 2>&1 && set PY=py -3 )
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )

if "%PY%"=="" (
  echo  [ERRO] Python nao encontrado. Rode o iniciar.bat uma vez primeiro.
  echo.
  pause
  exit /b 1
)

echo.
echo  Baixando a DRE da CVM. Leva alguns minutos na primeira vez.
echo  A saida tambem fica salva em diagnostico_bancos.txt
echo.

%PY% diagnostico_bancos.py > diagnostico_bancos.txt 2>&1
type diagnostico_bancos.txt

echo.
echo  ============================================================
echo   Pronto. O texto acima esta salvo em diagnostico_bancos.txt
echo   Abra esse arquivo, copie tudo e mande no chat.
echo  ============================================================
echo.
pause
