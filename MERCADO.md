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
| Dólar (PTAX venda) | Banco Central, SGS série 1 | todo dia útil |
| Meta Selic | Banco Central, SGS série 432 | a cada Copom, valendo todo dia |
| Expectativa de IPCA 12 meses | Banco Central, Focus pela API Olinda | semanal, publicada com alguns dias de atraso |

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

## O prêmio ao longo do tempo

A aba mostrava a diferença de juros prazo a prazo num dia. A outra metade é a
diferença num prazo fixo, dia a dia, desde dezembro de 2004 — `spread_historico.json`,
gerado na mesma coleta, sem nada acumulado entre execuções. Ele é reescrito do
zero todo dia, o que também quer dizer que se conserta sozinho: um erro
corrigido no cálculo reescreve os 21 anos na execução seguinte.

**As linhas não começam no mesmo ponto, e isso é dado.** Amostrando 45 datas ao
longo dos 21 anos:

| vértice | dias com dado | começa em |
|---|---|---|
| nominal 2 anos | 45 de 45 | 31/12/2004 |
| nominal 5 anos | 42 de 45 | 15/03/2006 |
| nominal 10 anos | **17 de 45** | 15/03/2010 |
| real 5 / 10 / 20 anos | 45 de 45 | 31/12/2004 |

O vértice **nominal** de 10 anos só existe quando há um título prefixado que
alcance esse prazo em oferta, e em boa parte do período não havia — em 2004 o
mais longo vencia em três anos, em 2009 em sete, em 2023 em nove. A linha
nominal de 10 anos é um tracejado cheio de falhas. Nesses dias ela some, em vez
de repetir o último valor: uma série de spread com o valor de ontem carregado
para a frente parece estabilidade e é ausência de dado.

Do lado **real** isso não acontece — a NTN-B vai a 2060 e o TIPS de 10 anos
existe desde 2003 —, e é por isso que os gráficos da seção seguinte, que são
todos de juro real, podem abrir em 10 anos sem tracejado.

A série bate com a história conhecida: pré de 2 anos a 17,5% no fim de 2004,
pico de 15,1% em setembro de 2015, mínima de 3,9% em setembro de 2020 (Selic a
2%), e 13,9% hoje. O prêmio nominal de 2 anos vai de 14,4 p.p. em 2004 a 3,7 no
fundo de 2020.

## A aba Brasil × EUA — três perguntas, três gráficos

A primeira versão mostrava o spread e mais nada, e não respondia às perguntas
que se faz olhando para um spread. A aba foi refeita em **22/09/2026** em torno
de três delas. Todas usam o mesmo `spread_historico.json`, agora com o dólar, a
meta Selic e a expectativa de inflação dentro.

**1. O juro real dos dois lados, e não só a diferença.** Três linhas: NTN-B,
TIPS e a diferença. Com só o spread na tela não dá para saber se ele subiu
porque o Brasil piorou ou porque os Estados Unidos melhoraram — e essas duas
coisas pedem decisões opostas. O padrão é **10 anos**: a ressalva que
derrubava o vértice de 10 anos no gráfico nominal (não há prefixado brasileiro
tão longo) não existe do lado real, onde a NTN-B vai a 2060 e o TIPS de 10 anos
existe desde 2003.

**2. O prêmio e o dólar, sem dois eixos verticais.** A tese é que prêmio maior
atrai capital e capital que entra derruba o dólar. O problema de desenho é que
p.p. e R$/US$ não têm conversão entre si: com dois eixos, quem desenha escolhe
onde as linhas se cruzam, e a escolha vira a conclusão. As duas séries aparecem
**padronizadas** — em desvios-padrão da própria média no período visível —, o
que põe as duas no mesmo eixo sem inventar câmbio nenhum entre as unidades. O
botão ao lado mostra as duas nas unidades originais, em gráficos separados.

Abaixo vem uma **correlação móvel de um ano entre as variações diárias**, não
entre os níveis. Em nível, duas séries com tendência no mesmo sentido dão
correlação alta sem qualquer relação entre elas; a pergunta de verdade é se
elas se mexem juntas, e isso se mede nas variações.

**3. O juro real e o ciclo da Selic.** As faixas de fundo são os ciclos de alta
e de queda da meta, extraídos da própria série pela `bcb.ciclos_da_selic` —
viradas de sinal, com os movimentos abaixo de 0,5 p.p. fundidos no vizinho para
não encher o gráfico de faixas de duas semanas. Desde dez/2004 saem **12
ciclos**, e eles batem um a um com a história: 19,75% em mai/2005, 8,75% em
jul/2009, 7,25% em out/2012, 14,25% em jul/2015, **2,00% em ago/2020**, 13,75%
em ago/2022, 15,00% em jun/2025, e a queda em curso.

Sobre as linhas: a meta Selic é nominal e de um dia. O que aperta a economia é
o juro **real**, e a tabela ciclo a ciclo compara o que a ponta curta fez com o
que a ponta longa fez — quando o juro longo cai durante um aperto, o mercado
comprou a história; quando sobe, não comprou.

### Juro real ex-ante

`(1 + pré 1 ano) ÷ (1 + IPCA esperado 12 meses) − 1`, que é a definição que o
próprio Banco Central usa. **Divisão, não subtração**: com juro de 14% e
inflação esperada de 4,62%, subtrair dá 9,38 e a conta certa dá 8,96 — quase
meio ponto num número que se discute em décimos.

O prefixado de 1 ano vem do Tesouro (o LTN mais próximo de um ano, interpolado)
e a inflação esperada vem do Focus. Nada de IPCA realizado: ex-ante é o juro
que se aceita hoje contra a inflação que se espera, e olhar para trás
responderia outra pergunta.

### Duas armadilhas das APIs do Banco Central

**O SGS recusa janela maior que 10 anos** em série diária — HTTP 406 com a
mensagem em português. Vinte e dois anos de dólar têm que ser pedidos em
pedaços (`bcb._fatiar`, oito anos por vez).

**O Focus devolve cada data duas vezes.** A tabela tem uma coluna
`baseCalculo`: 0 usa só quem respondeu nos últimos 30 dias, 1 usa uma janela
maior. Sem filtrar vêm 8.892 linhas para 5.700 dias úteis, com medianas
diferentes no mesmo dia — em 15/09/2015, 5,74 e 5,71. O número do Relatório
Focus, e o daqui, é o de `baseCalculo = 0`.

### A única série que repete valor

O resto do projeto não carrega valor para a frente. O Focus é a exceção
declarada: é apurado semanalmente e publicado com atraso (em 22/09/2026 o dado
mais recente era de 18/09), e não carregar significaria perder a ponta da série
toda semana. O limite é de dez dias corridos (`bcb.TOLERANCIA_FOCUS`); passou
disso, vira lacuna. O dólar e a meta Selic **não** são carregados — o dólar tem
valor em todo dia útil e a meta existe em todo dia do calendário.

### Um bug que ficou uma semana no ar

O robô gerava o `spread_historico.json` e o jogava fora: o passo de publicação
do `atualizar-mercado.yml` listava `mercado.json`, `pvp_historico.json` e
`ibov_carteira.json`, e o `git reset --hard origin/main` apagava o resto. A aba
mostrou "o arquivo ainda não existe" por uma semana inteira enquanto o robô o
produzia todo dia. Corrigido em 22/09/2026, junto com a reforma da aba.

Daí também o `conferir_historico` no `validar_mercado.py`: este arquivo não
aparece em cartão nenhum, só vira linha em gráfico, e **linha errada parece
linha**. Ele agora confere faixas, tamanho das séries, ordem das datas, saltos
impossíveis da meta Selic e buracos entre os ciclos.

### Ver a tela sem esperar a coleta

`python tests/fixture_spread.py` grava um `spread_historico.json` com a forma
exata do de verdade: Selic, dólar e Focus **reais**, curvas de juros
inventadas. Serve para conferir o JavaScript sem meia hora de download. O
arquivo sai marcado com `"demo": true` — a tela mostra aviso vermelho e o
`validar_mercado.py` sai com código 1, para que esquecer de apagá-lo não
publique 21 anos de número inventado.

## Histórico do P/VP — `gerar_pvp_historico.py`

A série do P/VP é acumulada pelo robô, um ponto por dia, e por isso nasce
vazia. Para reconstruir o passado existe o `gerar_pvp_historico.py`, que
**roda no seu computador**: a CVM recusa conexões de fora do Brasil e os
balanços antigos não podem ser baixados pelo GitHub Actions.

No Windows, duplo clique em **`pvp_historico.bat`**: ele roda o diagnóstico,
mostra a cobertura e pergunta antes de calcular. Pela linha de comando:

```
.venv\Scripts\python.exe gerar_pvp_historico.py --diagnostico --desde 2015
.venv\Scripts\python.exe gerar_pvp_historico.py --desde 2015
```

**Não use `python` solto.** As dependências estão no `.venv` do projeto, e no
Windows o `python` sem caminho cai no atalho da Microsoft Store — responde
"Python was not found" e não é Python nenhum. Todos os `.bat` do projeto
procuram o `.venv` primeiro pelo mesmo motivo.

O diagnóstico existe porque a execução é longa — centenas de MB de DFP e ITR —
e porque a cobertura ano a ano é a informação que decide se vale a pena. Ele
imprime, para cada ano, quantas empresas do índice têm patrimônio e nº de ações
e quanto do peso do índice isso cobre.

O cálculo respeita a data de entrega: em 02/01/2022 o balanço de 31/12/2021
ainda não era público e não entra no número daquele dia. É a mesma disciplina
do `backtest_historico.py`.

**O nº de ações vem da conciliação do cálculo diário, não da CVM ano a ano.**
A primeira versão lia `cvm.composicao_capital` por ano e devolveu *zero de 74
empresas em todos os anos* na primeira execução real — o arquivo da CVM é
indexado por **CNPJ**, não por código CVM, e o código procurava uma coluna que
nunca existiu, descartando cada ano em silêncio. A ponte CNPJ→CVM resolveria o
sintoma, mas o `composicao_capital` é justamente a fonte cuja escala não dá
para confirmar em parte das empresas (nula em 10 dos 76 papéis hoje, Vale e
Itaú entre eles). Como o nº de ações fica constante no tempo de qualquer jeito,
vale o número que o caminho diário já concilia — mesmo código, em produção.

Duas aproximações declaradas: o **nº de ações fica constante no tempo** (ele
muda com recompras e ofertas, devagar, e o histórico do Yahoo não distingue
ação de unit nem classe de total — trocaria um erro pequeno e conhecido por um
grande e invisível); e a **carteira do Ibovespa é a de hoje aplicada ao
passado**, com o viés de sobrevivência que isso traz.

O script recusa gravar uma série com menos de 100 pontos, e preserva os pontos
que o robô já tinha coletado — esses foram calculados com o `fundamentos.json`
do dia e valem mais que a reconstrução.

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

2. **O prefixo da B3 tem um dígito.** `magicb3.tickers` filtrava prefixos por
   `[A-Z]{4}` — quatro *letras*. O prefixo da B3 S.A. é `B3SA`. Ela pesa 3,3% do
   Ibovespa, tem R$ 18,8 bi de patrimônio na CVM (código 21610) e simplesmente
   não aparecia — nem no ranking, nem nas excluídas. `mercado/empresas.py`
   nasceu com `[A-Z][A-Z0-9]{3}`; o caminho das ações foi corrigido em
   **15/09/2026**, com o ranking mudando como consequência aceita.

   A conferência contra a API da B3 mostrou que o comentário que defendia a
   regra estreita estava errado: ela não filtrava emissor sem ação negociada.
   Das 3.189 companhias sem BDR que a API devolve, **3.111 passavam** por
   `[A-Z]{4}`, incluindo 2.612 SPEs e securitizadoras sem segmento. Quem faz
   esse corte é o passo seguinte do pipeline — só entra quem tem EBIT nos
   arquivos da CVM — e depois o filtro de liquidez. A regra larga admite 70
   prefixos a mais, dos quais 68 são SPEs sem DFP, que morrem ali. As duas
   companhias reais são **B3SA** e **B100**.

   O parquet em cache foi gravado com a regra antiga e não tem a B3 S.A., então
   o nome do arquivo mudou para `b3_empresas_v2.parquet` — o cache velho se
   aposenta sozinho. Ele ainda serve de recuo quando a B3 não responde, e nesse
   caso o log avisa que a B3SA não está nele. `tests/test_prefixos_b3.py`
   guarda a regra.

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

1. **Rodar o `gerar_pvp_historico.py`** uma vez, aqui. É o único passo que
   depende de você, e é o que tira a série do P/VP de dois pontos.
2. **Inflação implícita** — `(1 + pré) ÷ (1 + NTN-B) − 1` em cada vértice, com
   as duas curvas que já estão no arquivo. É o indicador que falta e sai quase
   de graça, inclusive na série histórica.
3. **Units sem nº de ações na CVM.** BPAC11 e SANB11 somam 3,2% do índice e
   saem por falta de um número que existe no formulário de referência.
4. **Carteira histórica do Ibovespa**, para tirar o viés de sobrevivência da
   série do P/VP. A B3 não publica em série; teria que ser acumulada daqui
   para a frente, um arquivo por quadrimestre.
5. **Fonte alternativa para a curva**, se o Tesouro mudar o CSV de lugar. O
   candidato é o DI futuro da B3.
