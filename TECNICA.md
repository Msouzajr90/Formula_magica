# Aba Análise técnica

Oitava aba do site (`tecnica.html`). Três partes: o gráfico de velas de uma
ação com os indicadores, o teste de uma regra de compra e venda no passado, e
o painel com o estado dos indicadores em todas as ações da base.

## Decisões do Marco (02/11/2026)

| tema | escolha |
|---|---|
| dados | fechamento **e** abertura, máxima, mínima e volume (o robô passa a gravar) |
| tela | gráfico por ação + painel de sinais de todas |
| universo | só ações (inclui units: TAEE11, KLBN11…); FIIs e ETFs fora |
| backtest | sim, das regras, contra comprar e segurar |

## Arquitetura

```
atualizar_precos.py ── simulacao.base.atualizar ── mesmo download do Yahoo
                                │
                                ├── precos/PETR4.json        (retornos, como antes)
                                └── tecnica.velas.Gravador → precos/ohlc/PETR4.json
                     tecnica.sinais.gravar ─────────────→ precos/ohlc/_sinais.json
navegador: tecnica.js + tecnica_motor.js (+ métricas de simulacao_motor.js)
```

* **Nenhuma requisição a mais ao Yahoo no dia a dia.** O `yf.download` já
  traz Open/High/Low; `magicb3.prices.baixar_historico` passou a devolvê-los.
  Na primeira execução depois da aba existir, as ações sem arquivo de velas
  têm o histórico inteiro baixado uma vez (5 lotes de 50). Ação que o Yahoo
  não devolve nem assim (deslistada) é anotada em `ohlc/_estado.json` e
  tentada de novo só depois de 30 dias.
* **Formato das velas**: abertura, máxima e mínima como razão para o
  fechamento do mesmo dia, em pontos-base; volume financeiro em R$ mil. As
  duas coisas não mudam quando o Yahoo reajusta o histórico por provento ou
  desdobramento — o arquivo só cresce no fim, como o de retornos. O preço
  ajustado vem da base de retornos e é multiplicado para o último ponto bater
  com o fechamento bruto (`ult`), em reais de hoje. ~90 KB por ação.
* **Painel** calculado pelo robô (200 ações × 90 KB seria pesado demais para
  o navegador baixar). O gráfico e o teste rodam no navegador, sobre os dois
  arquivos da ação escolhida.
* Publicação: o passo *Publicar* do `atualizar-precos.yml` passou a copiar a
  pasta recursivamente (`cp -r /tmp/precos/. web/public/precos/`) para levar
  `ohlc/`. Continua sem apagar nada.

## Indicadores

Médias simples 20/50/200 e exponenciais 9/21; Bollinger 20, 2 (desvio
populacional); IFR 14, ATR 14 e ADX 14 de Wilder; MACD 12, 26, 9; estocástico
lento 14, 3, 3; OBV sobre volume financeiro; máxima/mínima de 252 pregões;
canal de Donchian 55/20 (sem o próprio dia); força relativa contra o Ibovespa.
Médias exponenciais e Wilder começam pela média simples dos n primeiros
valores (Appel, Wilder, TradingView). Sem velas, estocástico, ATR, ADX e
volume ficam vazios no painel: com máxima = mínima = fechamento o +DI vira o
IFR, e isso não é ADX.

## Lacunas do Yahoo

Mesma regra da aba ETFs (10+ retornos zero seguidos, lacunas a até 3 pregões
se juntam). A história se divide em trechos limpos e cada indicador recomeça
em cada trecho. Na base de 02/11/2026, 40 das 205 ações têm lacuna em algum
momento (TEND3 2010–2017, NATU3 até 07/2025, AZTE3 até 11/2025…). O teste da
regra só roda no trecho limpo mais recente.

## Backtest

Sinal no fechamento de i, ordem na abertura de i + 1 (o dia se divide em
"noite" e "dia" com a razão abertura ÷ fechamento). Fora do mercado rende CDI,
creditado a quem dormiu fora. 15 bps por ponta, venda final. Regras: médias
(rápida × lenta, simples ou exponencial), preço × média, MACD × sinal, IFR
30/70, Bollinger (compra abaixo da banda, vende na média), rompimento
Donchian 55/20. Métricas da Simulação (`Motor.metricas`).

## Conferência

66 testes novos em `tests/test_tecnica.py` (597 na suíte):

* velas incrementais = velas completas; primeira execução sem velas baixa o
  histórico uma vez e chega ao mesmo resultado; desdobramento não muda as
  velas; abertura ajustada reconstruída bate com a fonte até o ponto-base;
* indicadores contra definições independentes (numpy, `pandas.ewm` depois da
  semente, ATR à mão, a identidade +DI = IFR sem velas);
* backtest: sempre fora = CDI exato; custo = (1 − 15 bps)^(2 × operações)
  exato; mudar o futuro não muda o passado; ordem na abertura seguinte;
* paridade Python × JS em 7 séries (sintética com velas, sintética com lacuna,
  PETR4, LREN3, TEND3, VALE3, WEGE3): indicadores a 1e-8, painel, e as 6
  regras do backtest a 1e-11. Mutações no JS (semente da média exponencial,
  custo só na compra, ordem no mesmo fechamento) derrubam a paridade.

Tela vista com a base real (sem velas) e com a demonstração (com velas), em
claro, escuro e celular.

## Próximos passos

1. Conferir a primeira base real de velas (quantas ações, pavios descartados).
2. Stop por ATR como opção das regras.
3. O mesmo teste de regra em todas as ações de uma vez (a resposta honesta a
   "a regra funciona?").
