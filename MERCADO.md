# Aba de indicadores de mercado

Terceira aba do site: o P/VP do Ibovespa, as curvas de juros prefixada e de
NTN-B em quatro datas, a diferença de juros entre Brasil e Estados Unidos e os
spreads de crédito privado — isentos × não isentos e por rating.

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
     |-- ANBIMA                -> debentures, NTN-B e curvas de credito
     |-- SND                   -> quem e incentivada (Lei 12.431)
              |
         mercado.json + pvp_historico.json + credito.json --> Vercel
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
| Curvas brasileiras | ANBIMA, `merc-sec/arqs/msAAMMDD.txt` (LTN, NTN-F, NTN-B), guardadas no acervo | todo dia útil, à noite; só sete ou oito pregões ficam no ar |
| Curvas brasileiras antigas e série desde 2004 | Tesouro Transparente, CSV de taxas do Tesouro Direto | parado desde 16/10/2026 (ver abaixo) |
| Curvas americanas | U.S. Treasury, *daily par yield curve* nominal e TIPS | fim da tarde de Nova York |
| Carteira do Ibovespa | B3, `GetPortfolioDay` | diária |
| Prefixo do ticker → código CVM | B3, `GetInitialCompanies` | muda devagar |
| Patrimônio líquido | `fundamentos.json` (CVM, DFP + ITR) | quando você roda `baixar_fundamentos.py` |
| Preços e valor de mercado | Yahoo | fechamento |
| Dólar (PTAX venda) | Banco Central, SGS série 1 | todo dia útil |
| Meta Selic | Banco Central, SGS série 432 | a cada Copom, valendo todo dia |
| Expectativa de IPCA 12 meses | Banco Central, Focus pela API Olinda | semanal, publicada com alguns dias de atraso |
| Taxa de cada debênture | ANBIMA, `merc-sec-debentures/arqs/dbAAMMDD.txt` | todo dia útil, à noite; cerca de cinco semanas ficam no ar (a janela muda) |
| NTN-B de referência | ANBIMA, `merc-sec/arqs/msAAMMDD.txt` | idem |
| Curvas de crédito AAA / AA / A | ANBIMA, `curvas-debentures/CD.asp` | depois do fechamento, às vezes no dia seguinte; mesma janela |
| Debênture incentivada ou não | SND, exportação de características | cadastro, muda devagar |

### Curvas brasileiras: ANBIMA e o acervo (desde 25/10/2026)

Até outubro de 2026 as quatro fotos da tela — hoje, uma semana, um mês e seis
meses atrás — saíam do CSV do Tesouro Transparente, que tem 21 anos de
histórico num arquivo só (~15 MB) e dispensava guardar qualquer coisa.

Em 16/10/2026 esse arquivo parou de ser atualizado (o último pregão é 15/10) e
o download passou a devolver uma página "429 – Muitas Requisições" no lugar
do CSV, também de um computador comum no Brasil. A coleta seguiu publicando a
curva de 15/10, com aviso, até o validador barrar a idade em 24/10.

Agora as curvas do dia vêm do `msAAMMDD.txt` da ANBIMA — o mesmo arquivo que
o crédito privado já baixava para as NTN-B. É a taxa **indicativa** de
mercado, melhor que a de varejo do Tesouro Direto. Mas a ANBIMA só deixa no ar
sete ou oito pregões, então o robô guarda o que vê em `juros.acervo`, dentro
do próprio `mercado.json` (o workflow já publica esse arquivo; não foi preciso
mexer no `.yml`). Regras (`mercado/titulos.py`):

- Um dia, uma fonte. Precedência: ANBIMA, depois Tesouro, depois "foto" —
  pontos recuperados das fotos de um `mercado.json` anterior. Foi assim que a
  primeira execução sem o Tesouro manteve as comparações de um mês e de seis
  meses: das fotos de 15/09 e 16/04 que já estavam publicadas.
- Guarda todos os pregões dos últimos 45 dias, um por semana de 45 a 220 dias,
  e sempre os dias que estão servindo de foto. Algumas dezenas de KB.
- Com o Tesouro de volta, os dias dele entram no acervo (abaixo da ANBIMA) e a
  série histórica da aba Brasil × EUA volta a ser refeita. Sem ele, essa série
  fica como está, com aviso — ela não tem como sair de oito pregões.
- O nome da foto diz a distância de verdade quando o pregão guardado mais
  próximo cai longe do alvo: "5 semanas atrás", não "1 mês atrás".
- Cada foto leva `fonteBR` ("ANBIMA" ou "Tesouro Direto"). Comparar uma foto de
  cada fonte mistura alguns pontos-base de diferença entre atacado e varejo
  com o movimento do mercado.
- A ANBIMA não traz a NTN-B Principal (o "Tesouro IPCA+" sem cupom); a curva
  real das fotos da ANBIMA é toda de títulos com cupom, marcados na tabela.

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

## Spreads de crédito privado — `credito.json`

Aba própria, incluída em **01/10/2026**: quanto uma empresa paga acima do
governo, separado em isentas × não isentas e por rating. Código em
`mercado/credito.py`, testes em `tests/test_credito.py` (sem rede, com
recortes reais em `tests/amostras/`).

### A ANBIMA não saiu do ar — só guarda uma semana

O texto acima diz que a ANBIMA saiu do ar para uso gratuito. Vale para o
formulário antigo (`merc-sec.asp`). Os **arquivos de texto** continuam
públicos, sem login, e respondem de fora do Brasil:

| arquivo | conteúdo |
|---|---|
| `/informacoes/merc-sec-debentures/arqs/db260930.txt` | taxa indicativa, duration e NTN-B de referência de ~1.290 debêntures |
| `/informacoes/merc-sec/arqs/ms260930.txt` | taxa indicativa de todos os títulos públicos |
| `/informacoes/curvas-debentures/CD.asp` (POST) | curvas de spread AAA, AA e A, de 0,5 a 10,5 anos |

O problema é outro: **só algumas semanas ficam no ar, e a janela muda**. Em
01/10/2026 o arquivo mais antigo era o de 22/09; em 20/10/2026 eram os de
14/09 — 25 pregões de debêntures, títulos públicos desde 11/09, curvas de
rating desde 14/09. Antes disso, 404. Não há série histórica gratuita. Por
isso o histórico do crédito é **acumulado**, como o do P/VP, e o
`credito.json` não pode ser perdido — está na lista do passo de publicação do
robô, com um teste que exige isso.

O robô procura **45 dias corridos** para trás (`credito.JANELA_DIAS`). Com os
12 dias da primeira versão, calibrados pela janela de 01/10, ele deixava três
semanas publicadas sem recolher. Cada execução recolhe todos os pregões da
janela e funde no arquivo: um dia que o robô perder volta na execução
seguinte. A curva de rating do dia D sai depois do robô de D; ela entra na
coleta de D+1, na linha de D.

Fontes que foram testadas para ir mais longe e **não servem** (20/10/2026):

* **Carteira do IDA** (`ida/IDA_result.asp`, "Resultado Diário por Índice"):
  traz a taxa de cada debênture do índice, mas na mesma janela de cinco
  semanas; o "download" devolve sempre a prévia da carteira atual.
* **Carteira do IMA-B**, para a NTN-B de cada vencimento: só uma semana. A
  série histórica do IMA (`ima-sh`) vai a anos atrás, mas é do índice, não de
  cada título.
* **Tesouro Direto** para a NTN-B: taxa arredondada a 0,01 e da manhã. Num
  spread que anda de 1 a 4 centésimos por dia, isso fabrica aberturas e
  fechamentos.
* **Internet Archive**: nenhuma cópia dos arquivos diários da ANBIMA.

### Abertura e fechamento: os mesmos papéis, não a mediana

A mediana do dia não diz se o mercado abriu ou fechou. O conjunto de papéis
muda — emissão nova entra na precificação, papel vence, resgate fica
exercível — e a mediana anda com a troca mesmo que nenhum spread se mexa.
Medido sobre os arquivos inteiros, de 14/09 a 19/10/2026:

| | mediana do dia | mesmos papéis |
|---|---|---|
| DI + spread | de 0,93 a 0,94, passando por 0,87 | **+0,8 bp** no período |
| IPCA isentas | **+77 bps** (0,09 → 0,86) | **+59 bps** |

Em 24/09 a mediana das DI+ caiu 4 bps com a entrada de 13 papéis novos,
enquanto os mesmos papéis abriram meio ponto. Nas isentas, 18 dos 77 bps
foram troca de papéis.

Por isso cada dia do histórico leva, além das medianas:

* `var_<grupo>` — mediana das variações de spread dos papéis que estavam no
  mesmo grupo no pregão anterior e neste (`credito.variacao_diaria`);
* `abriu_<grupo>` e `fechou_<grupo>` — a fração desses papéis que subiu ou
  caiu mais de meio ponto-base (a amplitude: um dia em que a mediana anda 1
  bp com 80% dos papéis abrindo não é o mesmo que um dia de 1 bp com metade
  para cada lado).

A tela encadeia as variações para trás a partir da mediana do último pregão
— o fim da linha coincide com os cartões — e marca os **episódios** de
abertura e fechamento em zigue-zague: um movimento só termina quando o
spread volta o mínimo escolhido (3, 5, 10 ou 20 bps) a partir do extremo.
Nas curvas de rating não há troca de papéis (prazo fixo), e a linha é a
própria curva.

A variação só é calculada entre dois pregões **vizinhos no histórico**: se um
dia do meio falhou na coleta mas está gravado de uma execução anterior,
comparar o seguinte com o anterior a ele contaria o movimento desse dia duas
vezes. Nesse caso a variação fica em branco e a corrente recomeça.

Conferência: um recorte real de 13 a 15/10/2026 (14 DI+ e 14 IPCA isentas,
`tests/amostras/anbima_db2610*_recorte.txt`) foi calculado à parte no
navegador; o código reproduz as medianas e as variações até a quarta casa
(`test_variacao_no_recorte_real`). O `validar_mercado.py` recusa variação
acima de 1 p.p. num dia (o maior de 14/09 a 19/10 foi +10 bps, nas isentas,
em 14/10) e frações de abertura e fechamento que somem mais de 1.

### O asterisco não é a isenção

O arquivo da ANBIMA marca nomes com `(*)` e `(**)`. A tentação é ler como
"incentivada". A legenda da página diz outra coisa: `(*)` é cláusula de
resgate ou amortização antecipada, `(**)` é cláusula já em período de
exercício. Quem diz se a debênture é incentivada é o **SND**: a exportação de
características (`caracteristicas_e.asp?op_exc=False`, 2,8 MB, tabulada)
traz a coluna **"Deb. Incent. (Lei 12.431)"** — 1.307 S e 3.503 N em
01/10/2026. Se o SND não responder, vale o cadastro guardado no próprio
`credito.json`; papel que não está em nenhum dos dois fica fora, em vez de
virar "não isenta" por omissão.

Rating de agência por papel não existe em dado aberto — o próprio ANBIMA Data
diz que "pode ser adquirido através das agências". A segmentação por rating é
a da curva de crédito da ANBIMA, com a classificação do comitê dela.

### O cálculo

* **DI + spread**: o spread é a própria taxa indicativa.
* **IPCA + spread**: taxa indicativa menos a NTN-B que a ANBIMA indica como
  referência daquele papel (coluna "Referência NTN-B"), no mesmo arquivo de
  títulos públicos do dia. Subtração, em p.p. — é como o mercado cota.
* **Mediana e quartis**, não média: no mesmo dia há Claro a DI + 0,36 e
  Equipav a DI + 5,48.
* **Faixas de duração** (até 3, 3 a 6, acima de 6 anos), porque as DI+ têm
  duração típica de 2,6 anos e as IPCA isentas de 5,2.
* **Equivalente bruto** das isentas: o spread que um papel tributado a 15%
  teria de pagar para render o mesmo depois do IR, passando pelo nominal
  (o IR incide sobre a inflação também) com o Focus de 12 meses.

Ficam fora, com a contagem no arquivo: sem taxa no dia (60), resgate já
exercível (107), duração abaixo de meio ano (31), % do DI / IGP-M / prefixado
(28), sem NTN-B de referência, e sem cadastro no SND.

### Conferência — 01/10/2026, arquivo inteiro

| grupo | papéis | mediana | quartis |
|---|---|---|---|
| DI + spread, não isentas | 469 | +0,90 p.p. sobre o DI | 0,62 – 1,47 |
| IPCA isentas | 578 | +0,46 p.p. sobre a NTN-B | 0,15 – 1,02 |
| — equivalente bruto | 578 | +2,64 p.p. | 2,29 – 3,25 |
| IPCA não isentas | 17 | +1,80 p.p. | 1,07 – 5,20 |
| Curva ANBIMA 3 anos (30/09) | | AAA 0,59 · AA 0,92 · A 1,91 | |

Os spreads de sete papéis da amostra foram conferidos um a um contra uma conta
feita à parte, no navegador, sobre o arquivo inteiro (ACRC21 +0,9466,
ALGE16 −0,0903, CSAN33 +2,4970…). Dois achados do dado:

1. **IPCA não isenta quase não existe** — 17 papéis contra 578 isentos. Na
   prática, isento × não isento é IPCA × DI. A tela diz isso e mostra o
   equivalente bruto para a comparação fazer sentido.
2. **As isentas abriram 23 centésimos numa semana** (0,23 em 22/09, 0,46 em
   01/10), com as DI+ paradas em 0,90. A NTN-B fechou e as taxas das
   debêntures não acompanharam no mesmo ritmo.

### Operação

```
python atualizar_mercado.py --so-credito   # só o credito.json
python verificar_mercado.py                # agora testa ANBIMA e SND também
python tests/fixture_credito.py            # arquivo de tela, "demo": true
```

O `validar_mercado.py` confere faixas das medianas (pega taxa no lugar de
spread), contagem mínima de papéis (pega cadastro cortado), a ordem AAA ≤ AA ≤ A
em todo vértice (pega coluna trocada) e o alinhamento do histórico.

**Próximos passos:** CRI e CRA (também isentos; a ANBIMA só os publica no
ANBIMA Data, que exige token); letras financeiras; e, quando o histórico tiver
alguns meses, o spread contra o ciclo da Selic.

## P/VP por papel — `pvp_papeis.json`

O gráfico "Histórico por papel", na aba P/VP, mostra o P/VP de uma ação semana
a semana desde 2015, com a mediana do período, a faixa entre os quartis (onde
o P/VP passou metade das semanas) e o ponto de hoje. Abre também pelo link do
ticker no ranking da página principal (`mercado.html#pvp=PETR4`).

**Quem gera o quê.**

| Peça | Onde roda | Frequência |
| --- | --- | --- |
| `gerar_pvp_papeis.py` (`pvp_papeis.bat`) — refaz a série inteira com os balanços da CVM | no seu computador (a CVM recusa o robô) | depois de cada temporada de balanços: fim de março, meados de maio, agosto e novembro |
| `atualizar_pvp_papeis.py` — grava o ponto da semana com o preço do `dados.json` e o VPA guardado | robô "Atualizar dados" | só às sextas |
| Ponto de hoje | o navegador: preço do `dados.json` ÷ VPA guardado | a cada coleta diária |

**A conta.** P/VP = fechamento × ações por papel ÷ (patrimônio dos
controladores ÷ ações). Três escolhas, cada uma com o motivo no código
(`mercado/pvp_papeis.py`):

- *Controladores, não consolidado.* O consolidado inclui a parte dos
  minoritários nas controladas. Na Cury (06/2026) são R$ 394 mi de
  R$ 2.049 mi; com o consolidado, o P/VP dela sairia quase 20% menor.
- *Point-in-time.* Cada semana usa o último balanço já entregue à CVM naquela
  data. Uma reapresentação de balanço antigo não faz o PL voltar no tempo.
- *Nº de ações de hoje.* O fechamento do Yahoo já vem ajustado por
  desdobramento, então essa parte bate; emissões e recompras, não. É a mesma
  aproximação do P/VP do índice, e a tela avisa.

Units entram só com o fator de ações por unit conhecido
(`ACOES_POR_UNIT_PAPEIS`) e nº de ações confirmado pela CVM. Quem fica de fora
aparece em `meta.fora` com o motivo, e a tela mostra esse motivo quando alguém
procura o papel.

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
ponto por dia), `credito.json` (histórico dos spreads e cadastro de
incentivadas), `ibov_carteira.json` e `mapa_cvm.json` (recuo para quando a B3
não responde). O passo de publicação do `.yml` copia os que o robô
reescreve: `pvp_historico.json`, `credito.json`, `ibov_carteira.json` e
`spread_historico.json`.

## O que a aba não olha

Risco de crédito soberano medido por CDS, inflação implícita explícita (dá
para tirar da diferença entre pré e NTN-B, mas a tela não calcula), e CRI/CRA
e letras financeiras no crédito privado (ver a seção de crédito). O P/VP usa patrimônio contábil — custo
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
