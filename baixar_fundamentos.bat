@echo off
REM ===================================================================
REM  Fundamentos da CVM -> web\public\fundamentos.json
REM  Precisa rodar AQUI, no Brasil: a CVM recusa conexoes do exterior.
REM  E a reserva do robo quando a CVM o recusa, e a fonte do P/VP do
REM  Ibovespa. Rode depois de cada temporada de balancos (fim de marco,
REM  meados de maio, agosto e novembro).
REM ===================================================================
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Fundamentos da CVM

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" ( where py >nul 2>&1 && set PY=py -3 )
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" (
  echo  [ERRO] Python nao encontrado. Rode o iniciar.bat uma vez primeiro.
  pause
  exit /b 1
)

echo.
echo  Baixando DFP e ITR dos tres ultimos anos. Leva alguns minutos.
echo.
%PY% baixar_fundamentos.py > fundamentos_log.txt 2>&1
set ERRO=%ERRORLEVEL%
type fundamentos_log.txt
echo.
if not "%ERRO%"=="0" (
  echo  [ERRO] Nao gravou. A mensagem acima diz por que; ela tambem esta em
  echo  fundamentos_log.txt - mande no chat se nao for obvio.
  pause
  exit /b 1
)
echo  Pronto: web\public\fundamentos.json foi gravado. Faca commit e push.
pause
