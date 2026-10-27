@echo off
REM ===================================================================
REM  Historico do P/VP de cada papel - reconstroi a serie semanal.
REM  Precisa rodar AQUI, no Brasil: a CVM recusa conexoes do exterior.
REM  Rode de novo depois de cada temporada de balancos (fim de marco,
REM  meados de maio, agosto e novembro): o robo do GitHub so move o
REM  preco, balanco novo so entra por aqui.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Historico do P/VP por papel

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

set DESDE=%1
if "%DESDE%"=="" set DESDE=2015

echo.
echo  Balancos da CVM desde %DESDE% (os anos que o pvp_historico.bat ja
echo  baixou vem do cache), mais os precos semanais de ~180 papeis no
echo  Yahoo. Leva de alguns minutos a meia hora. Nao feche esta janela.
echo.

%PY% gerar_pvp_papeis.py --desde %DESDE% > pvp_papeis_log.txt 2>&1
set ERRO=%ERRORLEVEL%
type pvp_papeis_log.txt

echo.
if not "%ERRO%"=="0" (
  echo  [ERRO] Nao gravou. A mensagem acima diz por que; ela tambem esta
  echo  em pvp_papeis_log.txt - mande no chat se nao for obvio.
  echo.
  pause
  exit /b 1
)
echo  ============================================================
echo   Pronto: web\public\pvp_papeis.json foi gravado.
echo   Faca commit e push pelo GitHub Desktop.
echo  ============================================================
echo.
pause
