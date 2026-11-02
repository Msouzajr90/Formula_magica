# Aba ETFs

Os fundos de índice da B3 lado a lado: quanto renderam, quanto oscilaram,
quanto caíram no pior momento, se entregam o índice que prometem e quais andam
juntos. Página `web/public/etfs.html`.

## Arquitetura: nenhum robô novo

A aba usa a **base de preços da Simulação** (`web/public/precos/`, robô
*Atualizar preços*) e calcula tudo no navegador (`etfs_motor.js`). O que é
novo fora da página é só a lista de ETFs:

```
web/public/etfs_catalogo.json   ← escrito à mão: nome, categoria, índice, grupo
        │
        ├─→ simulacao/config.py lê os códigos → o robô tenta baixar cada um
        └─→ etfs.js lê categoria e grupo → a tela
```

Uma fonte só: a aba nunca mostra ETF que o robô não procura, nem o contrário
(`test_robo_tenta_baixar_todo_o_catalogo`).

O catálogo tem 156 fundos (listagem da B3 em ivalor.com.br, mais os lançamentos
de 2025-26). Na base de 02/11/2026 havia 29; os outros 127 são tentados na
próxima execução do robô — entra quem tiver cotação no Yahoo e já tiver
passado de R$ 1 milhão/dia (média de 3 meses) em algum momento desde 2010. O
`PADRAO_TICKER` passou a aceitar código começando por dígito quando o sufixo é
11 (5GTK11, 5PRE11).

Para acrescentar um ETF: uma linha em `etfs_catalogo.json`.

| arquivo | |
|---|---|
| `web/public/etfs_catalogo.json` | a lista |
| `web/public/etfs_motor.js` | a conta (navegador e Node) |
| `web/public/etfs.html` + `etfs.js` | a tela |
| `simulacao/etfs.py` | a mesma conta em Python, por outro caminho; `python -m simulacao.etfs --janela 3a` imprime a tabela |
| `tests/test_etfs.py` + `paridade_etfs.mjs` | 35 testes, incluindo Python × JS nos arquivos publicados |

## O que a tela mostra

1. **Tabela** — liquidez, retorno de 1 mês, no ano, 12 meses, 3 e 5 anos (ao
   ano), volatilidade, queda máxima, Sharpe, correlação e beta com o Ibovespa.
   Filtro por categoria, busca, ordenação por qualquer coluna. Risco medido em
   12 meses, 3, 5, 10 anos ou todo o histórico.
2. **Gráfico** — retorno acumulado de até 8 ETFs marcados, contra Ibovespa e
   CDI. Cada ETF guarda a mesma cor enquanto estiver marcado.
3. **Correlação** — matriz dos marcados + Ibovespa.
4. **Aderência ao índice** — ETFs do mesmo índice comparados com o índice
   (Ibovespa; CDI para Tesouro Selic) ou com o mais antigo do grupo: diferença
   de retorno ao ano, tracking error, correlação.

Escolhas ficam no endereço (`?s=BOVA11,IVVB11&j=5a&g=max&c=exterior`).

## Decisões de método

- **Janela de N meses** começa no fechamento do mesmo dia N meses antes. ETF
  que não existia no começo fica sem número — mesmo princípio da cobertura
  mínima da aba Oportunidades.
- **Volatilidade, queda máxima, Sharpe**: retornos diários, as fórmulas da
  Simulação (Sharpe contra o CDI composto do mesmo período).
- **Correlação, beta, tracking error**: retornos de 5 pregões, contados de trás
  para a frente. ETF de S&P 500 fecha às 17h em São Paulo com Nova York aberta;
  no diário metade do movimento cai no dia seguinte e a correlação sai baixa.
- **Sem taxa de administração** (decisão do Marco, 02/11/2026). A aderência
  mostra o custo que de fato chegou ao investidor.
- CDI do último pregão sai um dia depois no SGS: repete-se a última taxa diária.

## O que os dados reais cobraram

**1. Lacunas do Yahoo.** IMAB11, B5P211 e IRFM11 têm **preço parado de
09/03/2022 a 23/10/2025** (909 pregões de retorno zero), um preço novo em
24/10/2025 (+33% a +49%), volta ao preço velho no pregão seguinte, mais 47
pregões parados, e o salto definitivo em 08/01/2026 (+36% a +53%). FIXA11 ficou
parado de 03/2022 a 01/2026. LFTS11 e DEBB11, de 09/2024 a 02/2025.

A primeira versão tratava esses saltos como desdobramento não ajustado e os
zerava — e com isso apagava quatro anos de retorno verdadeiro (IMA-B a 2,9% ao
ano em 3 anos). O salto **é** o retorno do período; o que não existe é o
caminho. Regra final: lacuna = 10+ retornos zero seguidos e o pregão do salto;
duas lacunas a até 2 pregões uma da outra viram uma. O retorno de ponta a
ponta vale se o preço de partida não estiver parado; volatilidade, queda,
Sharpe, correlação e aderência exigem período sem lacuna. No gráfico a linha se
interrompe e retoma no nível certo. Série que termina numa lacuna conta como
parada.

**2. Desdobramento não ajustado.** SPXI11 em 22/01/2026: −87,6% (1 para 8).
Fora de lacuna, salto acima de 15% (renda fixa) ou 40% (o resto) vira zero.

**3. ETFs de Ibovespa acima do índice.** Em 3 anos, BOVA11 +0,66 p.p./ano,
BOVV11 +0,70, BOVX11 +0,62 sobre o Ibovespa; XBOV11 −0,20. Em todo o
histórico (desde 2010) o BOVA11 fica em −0,03. Não há explicação confirmada;
receita de aluguel de ações é a candidata óbvia. Fica registrado.

## Conferência

- 35 testes novos; 535 no total. Paridade Python × JS até 1e-9 nos arquivos
  publicados em quatro janelas, num conjunto sintético com todos os casos
  (lacuna dupla, desdobramento, ETF novo, parado, fora da base, CDI atrasado)
  e na matriz de correlação e nas curvas. A paridade foi testada contra
  mutação: trocar o bloco de 5 por 4 pregões ou mexer 1e-7 no drawdown derruba
  os testes.
- BOVA11, 12 meses (+13,5%), volatilidade de 3 anos (18,6%) e queda máxima
  (−19,5%) refeitos à parte com pandas sobre o arquivo bruto: batem.
- Tela conferida no navegador (claro, escuro, celular), filtros, ordenação,
  marcação, estado no link, recarga.

## Achado para a aba Simulação

As lacunas não são só dos ETFs: **62 papéis** da base têm filas de 10+
retornos zero — TEND3 (1.788 pregões desde 2010), NATU3 (1.374 desde 2019),
TGAR11, CPTS11, AZEV3, TAEE3 entre os piores. Na Simulação isso aparece como
ativo de risco zero por anos seguido de um salto, e entra no Markowitz como
covariância falsa. `simulacao_motor.js` não trata. Próximo passo natural:
reaproveitar `lacunas()` no validador da base e avisar na tela da Simulação.

## Próximos passos

1. Rodar *Atualizar preços* e conferir quantos dos 127 ETFs novos entraram.
2. Lacunas na aba Simulação (acima).
3. Índices de referência de verdade para os grupos sem Ibovespa/CDI (S&P 500
   em reais = ^GSPC × PTAX; IMA-B da ANBIMA), para a aderência deixar de ser
   só entre pares.
4. Rebaixar o histórico completo (`--completo`) e ver se o Yahoo preencheu as
   lacunas dos ETFs de renda fixa da Itaú.
