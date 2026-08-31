# Auditoria do algoritmo — fórmula mágica + Markowitz

Revisão de `marco_completo.py` e da metodologia do TCC, com as correções
implementadas em `magicb3/`.

Resumo: a **arquitetura do trabalho está certa** — usar Greenblatt para
selecionar e Markowitz para alocar é uma combinação defensável e bem executada
no nível conceitual. O que compromete os resultados são erros de implementação
e três vieses metodológicos. Dois deles conseguem, sozinhos, explicar boa parte
do desempenho superior ao Ibovespa que o trabalho reporta.

---

## 1. Dúvidas do modelo, respondidas

### 1.1 O comentário no código: "checar se o 3.05 é melhor que 3.09 ou 3.11"

**3.05 está certo.** No plano de contas padronizado da CVM:

| Código | Conta | Serve para |
|---|---|---|
| 3.05 | Resultado Antes do Resultado Financeiro e dos Tributos | **EBIT** — é este |
| 3.09 | Resultado Líquido das Operações Continuadas | depois de juros e IR |
| 3.11 | Lucro/Prejuízo Consolidado do Período | lucro líquido |

Greenblatt usa EBIT justamente para comparar empresas com estruturas de capital
e cargas tributárias diferentes. 3.09 e 3.11 já embutem despesa financeira e
imposto, então uma empresa muito endividada pareceria pior no ROIC por um
motivo que não é operacional. O 3.05 continua no código como `C.CD_EBIT`.

Uma ressalva: 3.05 inclui equivalência patrimonial e "outras receitas/despesas
operacionais", que às vezes carregam itens não recorrentes (venda de ativo,
impairment). Para um filtro quantitativo isso é aceitável; se um resultado
parecer bom demais, vale abrir a DRE da empresa.

### 1.2 LPA é um substituto válido de Earnings Yield?

**Não.** Este é o erro mais grave do trabalho.

O Earnings Yield mede *preço*: quanto de lucro operacional se compra por real
investido. A fórmula é `EBIT / EV`. O LPA em reais (`lucro / nº de ações`) não
tem preço no denominador — ele só diz quanto lucro cabe em uma ação, o que
depende de quantas ações a empresa resolveu emitir.

Consequência prática: se uma empresa fizer um desdobramento de 1 para 10, o LPA
cai 10 vezes e ela despenca no ranking, sem que nada tenha mudado no negócio.
E se a ação dobrar de preço da noite para o dia — ficando o dobro de cara — o
LPA não se mexe, e ela continua com a mesma posição no ranking de "preço justo".

Há um teste automatizado que demonstra exatamente isso
(`test_ey_do_tcc_e_insensivel_ao_preco`): dobrando o valor de mercado de todas
as empresas, o "EY" do TCC não muda; o EY corrigido muda.

O efeito colateral é que o ranking de "EY" do TCC vira, na prática, um ranking
de **ações com valor nominal alto** — que na B3 tende a selecionar empresas de
capital fechado-ish, com poucas ações em circulação e baixa liquidez. Isso
conversa com a presença de papéis como ATOM4, CTKA3 e CTMN4 nas carteiras
reportadas, que são de liquidez muito baixa.

**Corrigido:** `EY = EBIT_12m / EV`, com `EV = valor de mercado + dívida bruta
− caixa e aplicações financeiras`.

### 1.3 ROIC calculado sobre o Ativo Total é aceitável?

É **ROA, não ROIC** — e o próprio Greenblatt explica no apêndice por que
rejeitou o ativo total. O ativo total inclui caixa ocioso, ágio de aquisições e
intangíveis que não são necessários para operar. Duas empresas idênticas em
geração de caixa, uma delas com R$ 5 bi parados no caixa, teriam ROA bem
diferentes sem nenhuma diferença operacional.

A fórmula do livro é:

```
ROIC = EBIT / (capital de giro líquido + ativo imobilizado líquido)

capital de giro líquido = (ativo circulante − caixa − aplicações financeiras)
                        − (passivo circulante − empréstimos de curto prazo)
```

Empréstimos de curto prazo saem do passivo circulante porque são financiamento,
não capital operacional; o caixa sai do ativo porque não é preciso para operar.
O giro é limitado a zero por baixo — empresas de varejo com giro negativo
(recebem antes de pagar) senão gerariam ROIC negativo com EBIT positivo.

**Corrigido:** `fundamentals.capital_tangivel()`. O ativo total continua
disponível como opção (`base_roic="ativo_total"`) para reproduzir o TCC.

### 1.4 Por que 2022 foi tão ruim se 2018–2021 e 2023 foram bons?

O TCC trata 2022 como "resultado esporádico". Vale considerar outra leitura: as
carteiras 2 a 50 da fronteira são construídas maximizando **retorno histórico
esperado**, estimado com um ano de retornos diários. Essa estimativa é
notoriamente ruidosa — o erro-padrão da média anual de retorno com 252
observações é da ordem de 20 pontos percentuais. Na prática, "maximizar retorno
esperado histórico" equivale a "concentrar no que mais subiu no ano passado".

Isso explica o padrão observado: em anos de continuidade de tendência (2018,
2019, 2023) as carteiras de maior risco vão muito bem; na virada de ciclo
(2022, com alta de juros) elas vão muito mal. A carteira 1 — mínima variância,
que não depende da estimativa de retorno — foi a única que ficou perto do
Ibovespa em 2022 (−0,9%), enquanto a carteira 10 perdeu 37,3%. Não é
coincidência: é a única que não usa o parâmetro ruidoso.

**Corrigido:** covariância com encolhimento de Ledoit-Wolf, retorno esperado
por média exponencial ou encolhida, e teto de peso por ativo.

### 1.5 As carteiras de maior risco realmente "buscam mais retorno"?

Em teoria sim, mas o TCC apresenta as 50 carteiras comparadas ao Ibovespa **sem
ajuste de risco**. A carteira 10 de 2018 rendeu 44,3% contra 12,8% do Ibovespa
— mas com que volatilidade? Sem essa informação não dá para dizer se houve
geração de valor ou apenas mais alavancagem em beta. Uma carteira com beta 2,0
num ano de alta de 12,8% do índice já entregaria ~25% sem nenhuma habilidade de
seleção.

**Corrigido:** a plataforma reporta volatilidade, Sharpe, beta, alfa, tracking
error, information ratio e drawdown máximo, para carteira e benchmark.

---

## 2. Erros de implementação

Ordenados por impacto no resultado.

### 2.1 O LPA nunca foi calculado — o código usou EBIT por ação

```python
dre_lpa = dre_cnpj[(dre_cnpj['CD_CONTA']=='3.99.01.01') & ...]   # calculado
df_lpa  = dre_roic[(dre_roic['DT_REFER']==data_base)]            # e ignorado
df_lpa['LPA'] = (df_lpa['VL_CONTA'] / df_lpa['ACOES_CIRC'])*1000
```

`dre_lpa` é montado e nunca usado. `df_lpa` parte de `dre_roic`, que está
filtrado em `CD_CONTA == '3.05'`. Ou seja, a coluna chamada "LPA" é
**EBIT dividido pelo número de ações**, não lucro por ação.

Além disso, se a intenção fosse usar a conta 3.99.01.01, ela **já é** o lucro
por ação em reais — dividir de novo pelo número de ações daria lucro por ação ao
quadrado por ação.

**Impacto: alto.** Metade do ranking de Greenblatt estava medindo outra coisa.

### 2.2 Escala monetária misturada entre DRE e Balanço

```python
dre_roic = dre_cnpj[(...) & (dre_cnpj['ESCALA_MOEDA']=='MIL') & (...)]
bp_roic  = bp_cnpj[(bp_cnpj['CD_CONTA']=='1') & (...)]     # sem filtro de escala
df_roic['ROIC'] = (df_roic['VL_CONTA'] / df_roic['VL_CONTA_BP'])*100
```

A CVM publica valores em `MIL` ou em `UNIDADE`, empresa a empresa. O numerador
foi restrito a MIL; o denominador aceita qualquer escala. Para toda empresa que
publica o balanço em UNIDADE, o ROIC saiu **1.000 vezes menor** que o real — e
essas empresas foram jogadas para o fim do ranking de ROIC por um erro de
unidade.

Pior: o filtro `ESCALA_MOEDA == 'MIL'` também **elimina do universo** todas as
empresas que reportam a DRE em UNIDADE. Elas nunca entraram na análise.

**Impacto: alto.** Distorce o ranking e reduz o universo silenciosamente.

**Corrigido:** `cvm._normalizar()` multiplica pelo fator da escala e normaliza
tudo para reais, com teste (`test_normaliza_escala_monetaria`).

### 2.3 Versões de arquivo duplicadas

A CVM publica refazimentos com `VERSAO` 2, 3, etc., mantendo a versão 1 no mesmo
arquivo. O script não filtra por versão, então empresas que republicaram
demonstrações aparecem duas ou três vezes. O `drop_duplicates()` posterior só
resolve quando os valores são idênticos — que é justamente o caso em que não
havia problema.

**Corrigido:** mantém apenas `VERSAO == max(VERSAO)` por empresa e data.

### 2.4 Betas atribuídos ao ticker errado

```python
for c in cotacao_empresas_raw:            # yfinance devolve colunas em ordem alfabética
    beta = beta.append({'Beta': ...})
beta.index = tickers                      # ordem do ranking, não alfabética
```

O laço percorre as colunas na ordem em que o `yfinance` devolveu (alfabética) e
depois cola o índice na ordem da lista `tickers` (ordem do ranking). A não ser
que as duas coincidam, cada beta fica atribuído a outra ação. O beta ponderado
da carteira, calculado a partir dessa tabela, também sai errado.

**Corrigido:** `backtest.betas_individuais()` alinha por nome de coluna, com
teste que embaralha a ordem e verifica que o resultado não muda.

### 2.5 Correlação calculada sobre preços, não sobre retornos

```python
cot_corr = pd.merge(cotacao_empresas_raw, cotacao_bench_raw, on="Date")
corr_carteira = cot_corr.corr(method='pearson')
```

Séries de preço são não estacionárias. Duas ações sem nenhuma relação, mas
ambas com tendência de alta no período, apresentam correlação de preço próxima
de 1. A matriz de correlação reportada no trabalho está inflada; a correlação
economicamente relevante é a dos retornos.

Há um teste que mostra o efeito: duas séries de retorno independentes
(ρ ≈ 0,03) geram séries de preço com correlação bem maior.

**Corrigido:** `backtest.matriz_correlacao()` usa retornos.

### 2.6 O retorno da carteira nunca é somado

```python
for i in range(np.size(rentabilidade_empresas, 1)):
    rent_port_ac[i] = port_zero * rentabilidade_empresas.iloc[:,i]
```

O resultado é uma matriz de contribuições ponderadas por ativo e por dia, que
vai direto para o Excel sem ser agregada. A soma por coluna precisaria ser feita
à mão na planilha. (A conta em si está certa para *buy-and-hold*: o retorno
acumulado da carteira é de fato `Σ wᵢ × retorno_acumuladoᵢ`. Mas isso deixa de
valer se houver rebalanceamento — há um teste que demonstra a diferença.)

### 2.7 Só a carteira 1 é de fato testada

```python
frontier_final = frontier_df.loc[(frontier_df.loc[:,0])>0]   # coluna 0 = carteira 1
tickers = list(frontier_final['TICKER'])
cotacao_empresas_raw = yf.download(tickers, ...)
```

Os tickers baixados para o backtest são apenas os com peso positivo na **carteira
1**. As carteiras 2 a 50 têm ações que não estão nessa lista, então seus retornos
não podem ser calculados por este código. As tabelas de 50 carteiras do trabalho
precisaram ser montadas por outro caminho.

### 2.8 Bibliotecas: o script não roda mais

| Linha | Problema |
|---|---|
| `yf.pdr_override()` | removido do yfinance desde a versão 0.2.51 |
| `pdr.get_data_yahoo(...)` | descontinuado junto com o `pdr_override` |
| `['Adj Close']` | o yfinance passou a usar `auto_adjust=True` por padrão e não devolve mais essa coluna |
| `DataFrame.append(...)` | removido no pandas 2.0 |
| `writer.save()` | removido no pandas 2.0 — agora é `writer.close()` |
| `!pip install riskfolio-lib` | sintaxe de notebook, não de script |

**Corrigido:** tudo reescrito para as versões atuais, e o `riskfolio-lib`
substituído por um otimizador próprio em scipy (menos de 100 linhas, sem
dependência de cvxpy).

### 2.9 Detalhes menores

- `rank_greenblatt_20 = rank_greenblatt[0:40]` — a variável diz 20, o corte é 40.
- Empates de ROIC ou EY recebem posições diferentes conforme a ordem em que as
  linhas caíram no DataFrame. Corrigido com `rank(method='min')`.
- `prices.T.dropna().T` elimina qualquer ativo com um único dia faltante,
  inclusive por leilão ou feriado local. Corrigido com um critério de cobertura
  mínima (80% dos pregões).
- Nenhuma restrição de peso máximo: nada impede a otimização de colocar 60% em
  um papel.
- Nenhuma restrição de peso mínimo: as carteiras ficam com dezenas de posições
  de 0,1%, que não são executáveis num lote padrão.
- `d=0.94` é passado para `assets_stats`, mas só tem efeito com `method='ewma'`;
  com `method='hist'` é ignorado.
- Nenhum custo de transação, corretagem, emolumento ou spread.

---

## 3. Vieses metodológicos

Estes não são erros de código — são características do desenho do estudo. São
os três pontos que mais afetam a credibilidade dos retornos reportados.

### 3.1 Viés de antecipação (*look-ahead bias*)

O desenho compra no 1º dia útil de 2018 usando o balanço de 31/12/2017. Esse
balanço só é entregue à CVM entre fevereiro e março de 2018 — o prazo legal da
DFP é o fim de março. Ninguém poderia ter montado essa carteira em 2 de janeiro.

O impacto é grande justamente porque a fórmula mágica seleciona por *preço
baixo*: uma empresa cujo resultado de 2017 foi ótimo mas ainda não divulgado
tende a subir quando o balanço sai. Comprar antes da divulgação captura esse
movimento de graça.

**Corrigido:** `backtest_historico.py` usa a coluna `DT_RECEB` (data de entrega
na CVM) para só considerar demonstrações efetivamente publicadas até a data da
compra. Quando `DT_RECEB` não existe, aproxima por +90 dias (anual) ou +45 dias
(trimestral). O parâmetro `--defasagem` permite exigir margem adicional.

Para a **carteira do dia**, que é o uso que você escolheu, isso deixa de ser um
problema por construção: a plataforma usa a última demonstração já divulgada e
a cotação mais recente. O `LTM` (DFP do último exercício fechado, ajustado pelos
ITRs trimestrais) mantém os indicadores com no máximo ~3 meses de defasagem, em
vez dos até 15 meses do desenho anual puro.

### 3.2 Viés de sobrevivência

A tabela CNPJ ↔ ticker foi montada manualmente em 2023 com as empresas listadas
naquele momento. Empresas que fecharam capital, faliram ou foram incorporadas
entre 2018 e 2022 simplesmente não existem no universo do backtest. Como
empresas que somem tendem a somir depois de desempenho ruim, isso empurra o
retorno da estratégia para cima em todos os anos testados.

A magnitude típica desse viés na literatura é de 1 a 4 pontos percentuais ao
ano, dependendo do período.

**Mitigado, não eliminado:** o universo agora é reconstruído a partir do
cadastro da CVM (que mantém as empresas com registro cancelado) somado à lista
da B3. Uma eliminação completa exigiria uma base histórica de composição do
mercado, que não existe gratuitamente. Está documentado como limitação.

### 3.3 Liquidez estática

A coluna `LIQUIDEZ` da planilha é um número fixo por empresa, aplicado
igualmente a 2018 e a 2022. Uma empresa que ficou líquida em 2021 passa no
filtro de 2018 com a liquidez de 2023 — o que é, de novo, informação do futuro.
E o corte de R$ 100 mil/dia é baixo demais: com esse volume, montar uma posição
de R$ 50 mil já move o preço.

**Corrigido:** o filtro recalcula o volume financeiro médio dos 63 pregões
anteriores a cada data, e o corte padrão subiu para R$ 1 milhão/dia
(configurável).

### 3.4 Bancos, seguradoras e utilities não foram excluídos

Greenblatt é explícito: essas empresas ficam de fora. Em um banco, a dívida é
matéria-prima, não financiamento — o EV não faz sentido. Em uma seguradora, o
"capital investido" é regulatório. Em uma concessionária de energia, o retorno
sobre capital é fixado pelo regulador, então o ROIC não mede qualidade de
gestão.

O TCC manteve todos. Isso aparece nas carteiras reportadas: BRAP4, ITSA4
(holdings financeiras), EGIE3, ELET6, ENEV3, TRPL4 (energia elétrica).

**Corrigido:** filtro setorial ligado por padrão, com a lista de padrões em
`config.SETORES_EXCLUIDOS_PADRAO` e um relatório de tudo que foi excluído e por
quê.

### 3.5 Número de ações vindo de planilha manual

`ACOES_CIRC` era digitado à mão. Não acompanha emissões, recompras nem
desdobramentos, e por isso o valor de mercado calculado a partir dele fica
errado ao longo do tempo.

**Corrigido, com ressalva:** a plataforma usa o número de ações do Yahoo
Finance. Para empresas com duas classes (ON e PN), o Yahoo às vezes reporta o
total consolidado e às vezes só a classe do ticker consultado, o que introduz
erro no EV. É a limitação conhecida mais relevante que sobra; para as ~30
empresas que entram na carteira final, vale a pena conferir o valor de mercado
uma vez por ano contra a B3 ou o site de RI.

---

## 4. O que muda na prática

| Item | TCC | Plataforma |
|---|---|---|
| Earnings Yield | LPA em R$ (na verdade EBIT/ação) | EBIT / EV |
| ROIC | EBIT / ativo total (= ROA) | EBIT / capital tangível |
| Período dos indicadores | anual, até 15 meses defasado | 12 meses móveis (DFP + ITR) |
| Escala monetária | misturada | normalizada para reais |
| Setores excluídos | nenhum | bancos, seguros, utilities |
| Liquidez | R$ 100 mil/dia, estática | R$ 1 mi/dia, janela móvel |
| Covariância | amostral | Ledoit-Wolf |
| Retorno esperado | média histórica | média exponencial / encolhida |
| Peso máximo por ação | ilimitado | 15% (ajustável) |
| Custo de transação | zero | 15 bps por ponta |
| Data da compra | 1º dia útil, com balanço não publicado | data de entrega na CVM |
| Métricas | retorno vs Ibovespa | + vol, Sharpe, beta, alfa, TE, IR, drawdown |
| Reprodutibilidade | planilhas manuais no Drive | tudo baixado das fontes oficiais |

Vale dizer com clareza: com essas correções, é **esperado** que os retornos
fiquem abaixo dos reportados no trabalho. A diferença é a medida do que vinha
dos vieses. A estratégia pode continuar batendo o Ibovespa — vários estudos da
fórmula mágica no Brasil encontram prêmio positivo mesmo com metodologia
rigorosa — mas com margem menor e com anos ruins mais frequentes.

---

## 5. Sugestões para uma próxima versão

Em ordem de custo/benefício:

1. **Rodar `backtest_historico.py` nas duas configurações** (original e
   corrigida) e reportar a diferença. Isso quantifica cada viés e daria um bom
   artigo — "quanto do prêmio da fórmula mágica na B3 é artefato metodológico".
2. **Testar rebalanceamento trimestral.** Greenblatt escalona as compras ao
   longo do ano justamente para diluir o risco de escolher um ponto ruim do
   ciclo. O desenho anual concentra tudo em janeiro.
3. **Comparar com uma alocação igualitária.** Greenblatt sugere pesos iguais. A
   pergunta natural do trabalho — "Markowitz agrega valor sobre 1/N?" — não foi
   respondida, e a literatura (DeMiguel, Garlappi & Uppal, 2009) sugere que
   muitas vezes não agrega. É um teste barato e um achado publicável de qualquer
   forma que dê.
4. **Incluir dividendos e o imposto de 15%.** O preço ajustado já reinveste
   proventos; o IR sobre ganho de capital na venda anual não está considerado e
   corrói de forma relevante um retorno de 20% ao ano.
5. **Testar HRP (Hierarchical Risk Parity)** como alternativa ao Markowitz. É
   mais robusto a erro de estimação e costuma ir melhor fora da amostra com
   poucos dados.
6. **Ampliar o benchmark.** Comparar também com o IBrX-100 e com um índice de
   *small caps* (SMLL), já que a fórmula mágica seleciona muita empresa média —
   comparar uma carteira de small caps só com o Ibovespa favorece a estratégia
   em anos de alta desse segmento.
