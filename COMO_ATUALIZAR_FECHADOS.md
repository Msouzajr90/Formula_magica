# Como atualizar a aba de fundos fechados

Duplo clique em **`baixar_fechados.bat`**, esperar, subir um arquivo para o
GitHub. É isso. O resto deste documento é o porquê de cada passo e o que fazer
quando algo sai errado.

## O ciclo

```
  SEU PC (Brasil)                      GITHUB                    VERCEL
  baixar_fechados.bat
     ↓ lê os informes da CVM
  fundos_fechados.json ─ você sobe ──→ fica no repositório ──────→ site
     (~560 KB, 1x por mês)                    ↓
                                        robô confere
                                     (não gera nada)
```

**Esta aba não tem robô que atualiza, e isso é de propósito.** Nas abas de
ações e de FII o robô do GitHub faz trabalho real: junta o informe da CVM com
preço e provento do Yahoo, e só então existe o arquivo do site. Aqui não há
etapa de mercado — fundo fechado de balcão não tem preço nem provento —, então
o `baixar_fechados.py` já produz o arquivo final. O robô só confere.

E ele não conseguiria fazer mais: `dados.cvm.gov.br` recusa conexões vindas de
fora do país, e o GitHub Actions roda nos Estados Unidos. É a mesma restrição
documentada em `COMO_ATUALIZAR_FIIS.md`.

## Quando rodar

Uma vez por mês, depois do dia 20. O informe mensal de FII e Fiagro sai até o
15º dia útil do mês seguinte; o de FIP é quadrimestral e muda três vezes por
ano.

Passar do prazo não quebra nada — patrimônio, cotistas e prazo mudam devagar.
O que envelhece é a rentabilidade do último mês. O robô avisa quando o arquivo
passa de 45 dias e reprova acima de 90.

## O passo a passo

1. **Duplo clique em `baixar_fechados.bat`.** Leva alguns minutos: o informe de
   FII sai do cache em `~/.fiib3_cache`, o de Fiagro baixa seis competências e
   o de FIP baixa o arquivo do ano.

2. **Leia o relatório.** Ele fica na tela e em `fundos_fechados.txt`. O que
   olhar, em ordem:

   - **"passam no filtro"** — se cair muito abaixo de 800, alguma fonte falhou;
   - **"Preenchimento das colunas que a tela usa"** — qualquer `[FALHA]` ali
     quer dizer que a CVM renomeou uma coluna;
   - **"Avisos"** — fundos com número estranho, já filtrados para o que vai
     mesmo para a tela.

3. **Suba o arquivo.** No GitHub: `web` → `public` → *Add file* → *Upload
   files* → arraste `fundos_fechados.json` → *Commit changes*.

4. **O robô confere sozinho.** O push dispara "Conferir fundos fechados", que
   roda os testes e o `validar_fechados.py`. Se ficar verde, a Vercel publica.
   Se ficar vermelho, abra o log: ele diz exatamente o que reprovou.

## Conferir antes de subir

```
.venv\Scripts\python.exe validar_fechados.py
```

É o mesmo script que o robô roda. Vale quando você mexeu em algum parâmetro e
quer ver o resultado antes de publicar.

## Ver a página localmente

Abrir o `fundos.html` com duplo clique **não funciona**: o navegador bloqueia a
leitura do JSON pelo protocolo `file://`. Sirva a pasta:

```
cd web\public
..\..\.venv\Scripts\python.exe -m http.server 8000
```

E abra `http://localhost:8000/fundos.html`.

## Quando algo sai errado

**"Python was not found"** — é o atalho falso da Microsoft Store. Use o `.bat`,
que acha o Python do `.venv` sozinho.

**Uma fonte falhou e as outras funcionaram** — o script segue com o que
conseguiu e registra o aviso. Um arquivo só com FII ainda é melhor que nenhum;
o relatório diz o que faltou.

**"pouquíssimos fundos"** — rode `sondar_fundos2.py`, que abre os arquivos da
CVM e imprime as colunas de cada um. Foi ele que pegou, na primeira rodada, que
`Prazo_Duracao` existe e vem preenchida no informe de FII mas é lixo no de
Fiagro.

**O robô reprovou por idade** — é só rodar o `.bat` de novo e subir.

## Parâmetros

O padrão publica **não exclusivo, 100 cotistas ou mais, público geral ou
qualificado** — 813 fundos na competência 08/2026. Para mexer:

```
baixar_fechados.py --cotistas-minimo 500     # universo menor
baixar_fechados.py --sem-fip                 # só FII e Fiagro
baixar_fechados.py --tudo                    # sem filtro nenhum
```

Se mudar o filtro no seu computador, mude também o mínimo em
`validar_fechados.py` — senão o robô reprova um arquivo que está certo.

O porquê de cada corte está em `fechados/config.py`, na classe
`ParamsFechados`, junto com as três tentativas que foram descartadas antes.
