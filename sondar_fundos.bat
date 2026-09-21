@echo off
REM ===================================================================
REM  Sondagem das fontes para a aba de fundos fechados (FII, Fiagro,
REM  FIP). So le e imprime; nao altera nenhum dado do site.
REM  De duplo clique neste arquivo.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Sondagem - fundos fechados

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
echo  Lendo o informe mensal de FII e Fiagro do cache e baixando o
echo  informe trimestral de FIP. O FIP nunca foi baixado antes, entao
echo  essa parte leva alguns minutos.
echo.
echo  A saida tambem fica salva em sondagem_fundos2.txt
echo.

%PY% sondar_fundos2.py > sondagem_fundos2.txt 2>&1
type sondagem_fundos2.txt

echo.
echo  ============================================================
echo   Pronto. O texto acima esta salvo em sondagem_fundos2.txt e o
echo   detalhe em amostra_fontes\fundos\resumo_fundos.json
echo  ============================================================
echo.
pause
