@echo off
REM ===================================================================
REM  Historico do P/VP do Ibovespa - reconstroi a serie diaria.
REM  Precisa rodar AQUI, no Brasil: a CVM recusa conexoes do exterior,
REM  entao o robo do GitHub nao consegue baixar os balancos antigos.
REM
REM  De duplo clique neste arquivo. Ele roda o diagnostico primeiro,
REM  que so relata a cobertura ano a ano, e pergunta antes de calcular.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Historico do P/VP do Ibovespa

REM O .venv primeiro: as dependencias (pandas, yfinance) estao nele, nao
REM no Python do sistema. E no Windows o "python" solto costuma cair no
REM atalho da Microsoft Store, que nao e Python nenhum.
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
echo  ============================================================
echo   Passo 1 de 2: diagnostico (nao calcula, nao grava nada)
echo  ============================================================
echo.
echo  Baixando DFP e ITR da CVM desde %DESDE%. Sao centenas de MB e
echo  leva varios minutos na primeira vez. Nao feche esta janela.
echo.

%PY% gerar_pvp_historico.py --diagnostico --desde %DESDE% > pvp_diagnostico.txt 2>&1
type pvp_diagnostico.txt

echo.
echo  ============================================================
echo   O texto acima esta salvo em pvp_diagnostico.txt
echo  ============================================================
echo.
echo  Se a cobertura do indice estiver boa nos anos que interessam,
echo  siga para o calculo. Se estiver baixa, pare aqui, abra o
echo  pvp_diagnostico.txt e mande no chat.
echo.
choice /c SN /m "Calcular e gravar a serie agora"
if errorlevel 2 goto fim

echo.
echo  ============================================================
echo   Passo 2 de 2: calculando a serie
echo  ============================================================
echo.
echo  Os balancos ja estao em cache, mas agora faltam os precos
echo  diarios de 76 papeis no Yahoo. Leva mais alguns minutos.
echo.

%PY% gerar_pvp_historico.py --desde %DESDE%
if errorlevel 1 (
  echo.
  echo  [ERRO] Nao gravou. A mensagem acima diz por que.
  echo.
  pause
  exit /b 1
)

echo.
echo  ============================================================
echo   Pronto. O web\public\pvp_historico.json foi atualizado.
echo   Confira o grafico antes de publicar e depois faca o commit.
echo  ============================================================
echo.

:fim
pause
