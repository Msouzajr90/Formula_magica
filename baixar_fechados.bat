@echo off
REM ===================================================================
REM  Gera o arquivo da aba de fundos fechados (FII, Fiagro e FIP).
REM  De duplo clique neste arquivo.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Fundos fechados

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
echo  Lendo os informes da CVM. O de FII e Fiagro sai do cache; o de FIP
echo  pode levar alguns minutos na primeira vez.
echo.

%PY% baixar_fechados.py > fundos_fechados.txt 2>&1
type fundos_fechados.txt

echo.
echo  ============================================================
echo   Pronto. O arquivo do site esta em
echo   web\public\fundos_fechados.json
echo   e este relatorio em fundos_fechados.txt
echo  ============================================================
echo.
pause
