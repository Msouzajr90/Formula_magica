# Aba de indicadores de mercado

Terceira aba do site: o P/VP do Ibovespa, as curvas de juros prefixada e de
NTN-B em quatro datas, e a diferença de juros entre Brasil e Estados Unidos.

Roda sozinha. Diferente da aba de FIIs, nada aqui precisa passar pela sua
máquina — as quatro fontes responderam de fora do Brasil quando este documento
foi escrito, e o robô do GitHub faz tudo. A única dependência local é o
`fundamentos.json`, que já é gerado para a aba de ações.

```
  GITHUB ACTIONS (todo dia util, 21h10 de Brasilia)
     |
     |-- Tesouro Transparente  -> curva prefixada e de NTN-B, 4 datas
     |-- U.S. Treasury         -> curva nominal e de TIPS
     |-- B3                    -> carteira teorica do Ibovespa
     |-- Yahoo                 -> precos e valor de mercado
     |-- fundamentos.json      -> patrimonio liquido (CVM), ja no repositorio
              |
         mercado.json + pvp_historico.json --> Vercel
```

## Por que não é tempo real

Você pediu tempo real. Não existe — não de graça, e não de fonte oficial.

A ANBIMA é a referência de mercado para taxas de títulos públicos e foi a
primeira tentativa. Os endereços antigos (`merc-sec.asp`, `est-termo/CZ.asp`)
respondem **404**: o formulário da página ainda aponta para eles, mas o
servidor não os serve mais. O portal novo (`data.anbima.com.br`) exige
credencial. E mesmo funcionando, a ANBIMA divulga uma prévia por volta das 13h
e a final por volta das 19h30 — nunca foi tempo real.

B3 e Tesouro também publicam no fechamento. O que existe de intradiário é o DI
futuro, por fonte não-oficial ou paga, e uma tela que se dissesse "tempo real"
com dado de fechamento estaria mentindo sobre a única coisa que quem olha não
tem como conferir. A aba mostra a data do fechamento ao lado de cada número.

## As fontes

| O quê | Onde | Quando sai |
|---|---|---|
| Curvas brasileiras | Tesouro Transparente, CSV de taxas do Tesouro Direto | todo dia útil de manhã, com o fechamento de D-1 |
| Curvas americanas | U.S. Treasury, *daily par yield curve* nominal e TIPS | fim da tarde de Nova York |
| Carteira do Ibovespa | B3, `GetPortfolioDay` | diária |
| Prefixo do ticker → código CVM | B3, `GetInitialCompanies` | muda devagar |
| Patrimônio líquido | `fundamentos.json` (CVM, DFP + ITR) | quando você roda `baixar_fundamentos.py` |
| Preços e valor de mercado | Yahoo | fechamento |

O CSV do Tesouro tem 21 anos de histórico num arquivo só (~15 MB). É de lá que
saem de graça as quatro fotos da tela — hoje, uma semana, um mês e seis meses
atrás — sem precisar guardar nada entre execuções.

O preço: são as taxas do Tesouro Direto, do varejo, não as indicativas do
mercado secundário da ANBIMA. Ficam alguns pontos-base distantes.

## Decisões que mudam o número

**Conversão de base.** O Treasury publica juro com capitalização semestral; a
taxa brasileira é efetiva ao ano. Subtrair uma da outra direto — o que quase
todo mundo faz — infla o spread em cerca de 6 pontos-base no vértice de 10
anos. A americana é convertida por `(1 + y/2)² − 1` antes de qualquer conta.

**A curva prefixada termina em 2037.** Cerca de onze anos: é o vencimento
prefixado brasileiro mais longo que existe, no varejo ou no atacado. O gráfico
mostra vinte anos e a linha acaba onde os dados acabam. Há um teste que falha
se a curva prefixada ganhar valor em 20 anos, e o `validar_mercado.py` recusa
publicar um arquivo assim — porque esticar a última taxa desenha uma reta com
cara de dado, e ninguém notaria.

**Zero-cupom na frente.** Onde o mesmo vencimento existe como LTN e como NTN-F,
vale a LTN: a taxa de um título com cupom é a TIR do fluxo inteiro, não a taxa
à vista daquele prazo. As de cupom entram só onde não há alternativa, e a tela
marca quais são.

**Títulos quase vencidos ficam de fora** — prefixado a menos de 3 meses, NTN-B
a menos de 1 ano. Ver "o que a primeira execução revelou".

## Como o P/VP do Ibovespa é calculado

Não existe série histórica gratuita e oficial. A B3 publica o indicador do dia
sem histórico; os sites que publicam a série não dizem como a calculam. Como o
projeto já tem o patrimônio líquido de 438 companhias da CVM e as cotações, o
número sai daqui — e sai auditável.

```
             Σ  qtd_i × preço_i
  P/VP  =  ───────────────────────        VPA = patrimônio líquido ÷ ações
             Σ  qtd_i × VPA_i
```

`qtd_i` é a quantidade teórica do papel no índice, já ajustada pelo free float.
Somar numerador e denominador separadamente é o que faz disto o P/VP *do
índice*, e não a média dos P/VP das empresas — que seria dominada pelas
pequenas e caras.

Bancos entram: para o ranking de Greenblatt eles saem porque ROIC e EV não
significam a mesma coisa num banco, mas o patrimônio líquido significa, e um
Ibovespa sem Itaú e Bradesco não seria o Ibovespa.

A série histórica é **acumulada**: cada execução do robô acrescenta o ponto do
dia em `pvp_historico.json`. Ela não nasce com passado — em seis meses tem seis
meses, coletados por nós.

## O que a primeira execução real revelou

A aba foi escrita sem acesso a nenhuma das fontes: o ambiente da sessão bloqueia
Tesouro, B3, Treasury e Yahoo. A conferência foi feita pelo navegador da máquina
do Marco, e derrubou cinco suposições. Vale registrar porque a maioria volta.

1. **A ANBIMA saiu do ar para uso gratuito.** `merc-sec.asp` responde 404. O
   formulário da própria página ainda aponta para ele. Toda a curva mudou de
   fonte por causa disso.

2. **O prefixo da B3 tem um dígito.** `magicb3.tickers` filtra prefixos por
   `[A-Z]{4}` — quatro *letras*. O prefixo da B3 S.A. é `B3SA`. Ela pesa 3,3% do
   Ibovespa, tem R$ 18,8 bi de patrimônio na CVM (código 21610) e simplesmente
   não aparecia. `mercado/empresas.py` usa `[A-Z][A-Z0-9]{3}`.
   **O mesmo filtro está no caminho das ações, e lá a B3 S.A. também está
   faltando — nem no ranking, nem nas excluídas.** Mexer nele muda o ranking de
   Greenblatt, então ficou para uma decisão separada.

3. **O nº de ações da CVM está nulo em 10 dos 76 papéis** — Vale e Itaú entre
   eles, juntos 19% do índice — e **mil vezes errado na Vivara** (235 bilhões de
   ações numa empresa de 235 milhões; P/VP 2.016). É o problema de escala que o
   `composicao_capital` documenta: o arquivo não tem coluna de escala e a
   inferência pelo lucro por ação nem sempre conclui. A solução foi uma segunda
   fonte independente — valor de mercado ÷ preço — e uma regra de conciliação
   em `pvp.acoes_da_empresa`: vale a da CVM quando as duas concordam, vale a
   implícita quando divergem mais de duas vezes ou quando a da CVM não existe.
   A Sabesp, com 5x de divergência, saiu de P/VP 0,49 para 2,46.

4. **Unit não é ação.** A KLBN11 é 1 ON + 4 PN; a quantidade teórica do índice
   está em units, e cada unit carrega o patrimônio de cinco ações. Sem o fator,
   ela aparecia com P/VP 10,4 em vez de 2,1. Os fatores estão em
   `pvp.ACOES_POR_UNIT`, e uma unit fora da lista é **excluída**, não chutada.
   Units também exigem o nº de ações da CVM: o implícito no valor de mercado
   não diz se está contando units ou ações, e para a BPAC11 os dois candidatos
   dão P/VP 0,99 e 2,96 sem nada no número que diga qual.

5. **NTN-B curta não é ponto da curva real.** Em 14/08/2026 a NTN-B que vencia
   no dia seguinte marcava 13,32% de juro real; em 16/03/2026 a de cinco meses
   marcava 9,88%, contra 8,21% da seguinte. A correção pelo IPCA é defasada, e
   numa NTN-B curta a "taxa real" mede a defasagem do índice, não o juro. Sem o
   corte, o vértice de 1 ano da curva real saía perto de 10% num gráfico em que
   todo o resto está entre 7% e 8% — e o desenho não denunciava nada.

## Conferência dos números

Fechamento de 14/09/2026, checado contra o mercado:

| | |
|---|---|
| Pré 10 anos | 14,44% (NTN-F 2035 e 2037 a 14,44%) |
| NTN-B 10 anos | 7,59% |
| Treasury 10 anos | 5,03% efetivo (4,97% na base do Treasury) |
| TIPS 10 anos | 2,62% |
| Spread nominal 10 anos | +9,41 p.p. |
| Spread real 10 anos | +4,97 p.p. |
| P/VP do Ibovespa | 1,62, cobrindo 94,7% do peso do índice |

Empresa por empresa: Vale 1,54, Itaú 2,21, Petrobras PN 1,59, Bradesco PN 1,13,
Banco do Brasil 0,68, WEG 9,58. Batem com o mercado.

Fora do cálculo, 5,3% do índice: ASAI3 e BRAP4 (não estão no
`fundamentos.json`), BPAC11, ENGI11 e SANB11 (units sem nº de ações na CVM),
BEEF3 (patrimônio líquido negativo) e TIMS3 (patrimônio zerado na extração).

## Operação

Nada a fazer no dia a dia. O robô `Atualizar mercado` roda 21h10 de Brasília, de
segunda a sexta, meia hora depois do dos FIIs para não brigarem pelo push.

```bash
python verificar_mercado.py     # testa as quatro fontes, uma a uma
python atualizar_mercado.py     # gera o mercado.json
python validar_mercado.py       # confere se os números são possíveis
python atualizar_mercado.py --demo       # números sorteados, para ver a tela
python atualizar_mercado.py --sem-pvp    # só as curvas de juros
```

Os três blocos são independentes: se o P/VP falhar, as curvas são publicadas
com o aviso no arquivo, e a aba mostra o aviso no topo da página.

**Arquivos acumulados que o robô não pode perder:** `pvp_historico.json` (um
ponto por dia), `ibov_carteira.json` e `mapa_cvm.json` (recuo para quando a B3
não responde). O passo de publicação do `.yml` copia os três.

## O que a aba não olha

Risco de crédito soberano medido por CDS, câmbio, inflação implícita explícita
(dá para tirar da diferença entre pré e NTN-B, mas a tela não calcula), e
qualquer curva de crédito privado. O P/VP usa patrimônio contábil — custo
histórico corrigido, não valor de reposição — e a série histórica, quando
existir, usará a carteira atual do Ibovespa aplicada ao passado, com o viés de
sobrevivência que isso traz.

**Próximos passos, em ordem de valor:**

1. **Inflação implícita** — `(1 + pré) ÷ (1 + NTN-B) − 1` em cada vértice, com
   as duas curvas que já estão no arquivo. É o indicador que falta e sai quase
   de graça.
2. **Backfill do P/VP.** A série começa hoje. Reconstruir o passado exige o
   patrimônio líquido de cada trimestre respeitando `Data_Entrega` e o preço na
   data — a mesma disciplina *point-in-time* do `backtest_historico.py`.
   `pvp.painel_patrimonio` e `pvp.patrimonio_vigente` já existem para isso.
3. **Units sem nº de ações na CVM.** BPAC11 e SANB11 somam 3,2% do índice e
   saem por falta de um número que existe no formulário de referência.
4. **Fonte alternativa para a curva**, se o Tesouro mudar o CSV de lugar. O
   candidato é o DI futuro da B3.
