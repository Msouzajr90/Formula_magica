# Aba Simulação

Você escolhe os ativos; o site faz o backtest e mostra as métricas. Diferente
da aba de ações, nada aqui seleciona ativo: a escolha é sua, o sistema só
refaz o passado com ela.

```
  GITHUB (robô "Atualizar preços", dias úteis 21h40)        VERCEL
  atualizar_precos.py
     ↓ Yahoo (preço ajustado, volume) + Banco Central (CDI)
  web/public/precos/ ── validar_precos.py ── push ──────→ simulacao.html
                                                            ↓
                                              navegador baixa só os papéis
                                              escolhidos e roda o motor
                                              (simulacao_motor.js, num Worker)
```

Roda **inteiro na nuvem**: Yahoo e Banco Central respondem de fora do Brasil.
Nada a fazer no PC.

## O que a tela faz

| escolha | opções |
|---|---|
| ativos | qualquer papel da base; vários de uma vez separados por vírgula |
| pesos | **informados** (campo em branco divide o que falta para 100% em partes iguais) ou **Markowitz** |
| Markowitz | mínima variância · máximo Sharpe · volatilidade-alvo; teto por ativo (15% padrão) |
| rebalanceamento | comprar e segurar · mensal · trimestral · anual |
| custo | bps por ponta (15 padrão) |
| período | datas livres ou atalhos 1/3/5/10 anos/máximo |

Resultado: retorno acumulado e queda desde o pico (carteira, Ibovespa, CDI);
tabela de métricas nas três colunas; por ativo (peso inicial/médio/final,
contribuição ao retorno e ao risco, retorno, volatilidade, beta, queda
máxima); pesos ao longo do tempo; correlação dos retornos; tabela mês a mês;
retorno e volatilidade em janelas de 12 meses.

A configuração mora no endereço (`?a=PETR4:30,VALE3&m=man&r=t&c=15&de=…`):
favorito ou link reabrem a mesma simulação. Nada é guardado em servidor.

## Decisões de método

**Convenção de datas.** Compra no fechamento do pregão inicial; o primeiro
retorno é o do pregão seguinte. Rebalancear é voltar ao alvo no fechamento do
primeiro pregão de cada mês, trimestre ou ano. Entre rebalanceamentos os pesos
andam com os preços.

**Markowitz não olha para o futuro.** Os pesos da data *k* saem só dos 252
retornos até *k* (Ledoit-Wolf + média exponencial, o mesmo estimador da aba de
ações), e são refeitos a cada rebalanceamento. Se algum ativo não tem 12 meses
de histórico na data pedida, o início é adiado — com aviso — em vez de o ativo
ser descartado: a carteira simulada é a que você montou. Teste:
`test_markowitz_nao_olha_para_o_futuro` muda os retornos depois de uma data e
confere que os pesos até ela não mudam.

**Máximo Sharpe com todo Sharpe negativo.** Se nenhuma combinação dos ativos
tinha retorno esperado acima do CDI na janela, o "máximo" seria o menos
negativo — e dividir um excesso negativo por mais risco o aproxima de zero, ou
seja, o máximo apontaria para a carteira mais arriscada. Nesses casos fica a de
mínima variância, e a tela diz em quantas datas isso aconteceu. No Brasil, com
CDI de dois dígitos, acontece bastante.

**Custo.** Sobre o valor negociado: 100% na compra, Σ|alvo − atual| em cada
rebalanceamento, 100% na venda final. Igual ao `magicb3.backtest`.

**Sharpe, Sortino e alfa** usam o CDI composto do mesmo período como taxa livre
de risco. Sortino: só a volatilidade dos dias abaixo do CDI. Alfa de Jensen.
Captura de alta/baixa: média geométrica mensal da carteira ÷ do Ibovespa, nos
meses em que o Ibovespa subiu/caiu. VaR e CVaR históricos de 1 dia.

**Contribuição ao retorno** soma exatamente o retorno total quando se descontam
os custos (é a variação em reais de cada posição, em fração do capital
inicial). **Contribuição ao risco** usa o peso médio do período e a covariância
dos retornos diários; soma 100%.

## A base de preços

```
web/public/precos/
  indice.json   calendário de pregões, lista de ativos, recusados, avisos
  PETR4.json    {"t","i0","esc","r":[inteiros]}   um arquivo por papel
  _IBOV.json    Ibovespa
  _CDI.json     CDI (SGS 12), escala 1e8
```

**Por que retorno e não preço.** O preço ajustado do Yahoo é reescalado inteiro
a cada provento; gravando preço, todo papel com dividendo reescreveria o
arquivo inteiro e o repositório cresceria megabytes por dia. O retorno diário
não muda com a reescala: o arquivo só cresce no fim. `r[k]` é o retorno do
pregão `i0 + k` do calendário, inteiro com escala 1e6 (erro de 5e-7 por dia,
aleatório). O CDI usa 1e8 porque o erro de arredondamento dele seria sempre o
mesmo, todo dia, na mesma direção.

**Quem entra.** Candidatos: os papéis que as outras abas conhecem
(`dados.json`, carteira do Ibovespa, `pvp_papeis.json`, `fiis.json`), os irmãos
de classe das ações (PETR3 ao lado de PETR4), 30 ETFs listados em
`simulacao/config.py` e o que você puser em **`simulacao/tickers_extras.txt`**
(BDRs, por exemplo). Entra quem passou de **R$ 1 milhão por dia** de volume
médio (63 pregões) **em algum momento desde 2010**.

**A base é acumulativa.** Papel que entrou não sai porque saiu das listas de
hoje, e se o Yahoo deixar de devolvê-lo (deslistado, incorporado), o arquivo
antigo fica. É o que permite simular 2015 com papéis que não existem mais.
Limite que sobra: empresas que fecharam capital **antes da primeira coleta**
não estão — o Yahoo já não tem o histórico delas.

**Atualização diária incremental.** O robô baixa só os últimos 100 dias de quem
já está na base e emenda no fim; candidato novo baixa o histórico inteiro e
passa pelo corte; recusado só é reavaliado depois de 30 dias. O teste
`test_incremental_igual_ao_completo` confere que atualizar dia a dia dá
exatamente os mesmos arquivos que rebaixar tudo de uma vez.

**Saltos.** Variação diária acima de 40% não é corrigida — pode ser verdade
(Americanas, jan/2023) ou desdobramento que o Yahoo não ajustou. Fica marcada
no índice e aparece ao lado do ativo na tela, com a data, para conferir.

## Operação

| quando | o quê |
|---|---|
| depois do push | Actions → **Atualizar preços** → Run workflow. A primeira execução baixa tudo desde 2010 (10–20 min) |
| todo dia útil | o robô roda sozinho às 21h40 |
| validador pediu reconstrução, ou desdobramento corrigido no passado | Run workflow com **completo** marcado |
| quer um papel que não está | acrescente em `simulacao/tickers_extras.txt`, publique, rode o robô |
| ver a tela sem esperar a coleta | `python atualizar_precos.py --demo` grava uma base inventada (marcada em vermelho; o validador recusa publicar) |

O validador (`python validar_precos.py`) barra a publicação se: base de
demonstração, último pregão com mais de 8 dias, Ibovespa atrás do calendário,
CDI parado há mais de 5 pregões ou fora de 0,5%–40% ao ano, índice que não bate
com o arquivo, menos de 100 ativos, ou menos de 80% dos ativos chegando ao
último pregão.

## Arquivos

| | |
|---|---|
| `simulacao/config.py` | parâmetros, cada um com o porquê |
| `simulacao/series.py` | preço → retorno no calendário, emenda, liquidez, CDI (puro) |
| `simulacao/universo.py` | candidatos |
| `simulacao/base.py` | monta e atualiza a base |
| `simulacao/coleta.py` | a única parte que toca a rede |
| `simulacao/demo.py` | fontes falsas, para a demonstração e os testes |
| `atualizar_precos.py`, `validar_precos.py` | o que o robô roda |
| `web/public/simulacao.html`, `simulacao.js` | a tela |
| `web/public/simulacao_motor.js` | o cálculo (puro; roda no navegador e no Node) |
| `web/public/simulacao_worker.js` | roda o motor fora da linha principal |
| `tests/test_simulacao_base.py` | 33 testes da base, sem rede |
| `tests/test_simulacao_motor.py` + `paridade_simulacao.mjs` | 20 testes do motor JS contra o Python |

A paridade confere: o otimizador idêntico ao do `app.js`; Ledoit-Wolf e média
exponencial iguais ao `magicb3.optimizer` (1e-10); mínima variância igual ao
scipy; máximo Sharpe e volatilidade-alvo no ótimo do scipy; métricas iguais ao
`magicb3.backtest.calcular_metricas` (1e-9); comprar e segurar igual ao
`magicb3.backtest.retorno_carteira`; rebalanceamento igual a uma referência
independente em pandas (1e-13).

## O que não está aqui

- **Imposto de renda** sobre vendas nos rebalanceamentos e sobre proventos.
  Rebalancear com frequência parece melhor na tela do que é.
- **Aportes periódicos.** Ficou fora na validação inicial; o motor já separa
  valor por ativo e caixa, então é uma extensão direta.
- **HRP** e **pesos iguais com teto** como alternativas ao Markowitz.
