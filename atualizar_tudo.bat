@echo off
REM ===================================================================
REM  Atualiza tudo o que precisa da CVM - roda AQUI, no Brasil.
REM  1) fundamentos.json  (balancos atuais: ranking e P/VP do Ibovespa)
REM  2) pvp_papeis.json   (historico de P/VP de cada papel)
REM  3) pvp_historico.json (historico do P/VP do Ibovespa) - opcional
REM  4) commit, push e disparo dos robos do GitHub - tudo num clique.
REM ===================================================================
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Atualizar tudo

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
echo  ============================================================
echo   1 de 3 - Fundamentos da CVM (fundamentos.json)
echo  ============================================================
%PY% baixar_fundamentos.py > fundamentos_log.txt 2>&1
if errorlevel 1 (
  type fundamentos_log.txt
  echo.
  echo  [ERRO] Os fundamentos nao foram gravados. Parei aqui: o resto
  echo  depende deles. Mande o fundamentos_log.txt no chat.
  pause
  exit /b 1
)
echo  OK - detalhes em fundamentos_log.txt

echo.
echo  ============================================================
echo   2 de 3 - Historico de P/VP por papel (pvp_papeis.json)
echo  ============================================================
%PY% gerar_pvp_papeis.py --desde 2015 > pvp_papeis_log.txt 2>&1
if errorlevel 1 (
  type pvp_papeis_log.txt
  echo.
  echo  [ERRO] O historico por papel nao foi gravado. Mande o
  echo  pvp_papeis_log.txt no chat.
  pause
  exit /b 1
)
findstr /c:"semanas" /c:"Fora" pvp_papeis_log.txt

echo.
echo  ============================================================
echo   3 de 3 - Historico do P/VP do Ibovespa (opcional, demorado)
echo  ============================================================
echo  So precisa quando mudou o calculo ou entrou balanco antigo
echo  corrigido. O robo ja acrescenta o ponto de cada dia.
choice /c SN /m "Refazer o historico do P/VP do Ibovespa agora"
if errorlevel 2 goto fim
%PY% gerar_pvp_historico.py --desde 2015 > pvp_historico_log.txt 2>&1
if errorlevel 1 (
  type pvp_historico_log.txt
  echo  [ERRO] Nao gravou o historico do indice; o resto ja esta pronto.
  pause
  exit /b 1
)
echo  OK - detalhes em pvp_historico_log.txt

:fim
echo.
echo  ============================================================
echo   Publicando (commit e push)
echo  ============================================================
REM O git de linha de comando, ou o que vem dentro do GitHub Desktop.
set GIT=
where git >nul 2>&1 && set GIT=git
if not defined GIT (
  for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
    if exist "%%D\resources\app\git\cmd\git.exe" set GIT="%%D\resources\app\git\cmd\git.exe"
  )
)
if not defined GIT goto manual

REM So o que e do projeto: codigo, paginas e dados. Logs ficam fora (.gitignore).
%GIT% add -A -- magicb3 mercado tests web *.py *.bat *.md .gitignore
%GIT% diff --cached --quiet && (
  echo  Nada novo para publicar.
  goto robos
)
%GIT% commit -m "Atualizacao local: fundamentos e historicos de P/VP" >nul
REM O robo pode ter publicado o dados.json enquanto isto rodava: traz antes de enviar.
%GIT% pull --rebase --autostash origin main
if errorlevel 1 (
  %GIT% rebase --abort >nul 2>&1
  echo  [AVISO] O GitHub tem mudancas que nao encaixaram sozinhas.
  goto manual
)
%GIT% push origin main
if errorlevel 1 goto manual
echo  Publicado.

:robos
echo.
echo  ============================================================
echo   Robos do GitHub
echo  ============================================================
where gh >nul 2>&1
if errorlevel 1 (
  echo  Se o fundamentos.json mudou, os robos "Atualizar dados" e
  echo  "Atualizar mercado" disparam sozinhos com o push. Se nao mudou,
  echo  eles rodam no horario de sempre - ou em Actions, Run workflow.
  goto fim2
)
gh workflow run "Atualizar dados" && gh workflow run "Atualizar mercado"
if errorlevel 1 (
  echo  [AVISO] Nao consegui disparar os robos pelo gh; rode em Actions.
) else (
  echo  Robos disparados. Em alguns minutos o site mostra os dados novos.
)
goto fim2

:manual
echo.
echo  Nao consegui publicar daqui. Abra o GitHub Desktop e clique em
echo  Push origin - os arquivos ja estao prontos e o commit ja foi feito
echo  quando foi possivel.
if exist "%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe" start "" "%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe"

:fim2
echo.
pause
