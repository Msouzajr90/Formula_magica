@echo off
REM ===================================================================
REM  Sondagem 2 - informe de FIP atual (quadrimestral) e Fiagro por
REM  competencia. So le e imprime; nao altera nada do site.
REM  De duplo clique neste arquivo.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Sondagem 2 - FIP e Fiagro

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
echo  Procurando o informe de FIP atual e conferindo seis competencias
echo  de Fiagro. Leva alguns minutos.
echo.

%PY% sondar_fip.py > sondagem_fip.txt 2>&1
type sondagem_fip.txt

echo.
echo  ============================================================
echo   Pronto. Salvo em sondagem_fip.txt e em
echo   amostra_fontes\fundos\resumo_fip.json
echo  ============================================================
echo.
pause
