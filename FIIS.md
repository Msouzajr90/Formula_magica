# Fundos imobiliários

Segunda aba do site, com o mesmo desenho da primeira: o Python baixa e trata,
o navegador ranqueia e simula.

```
verificar_fiis.py      diagnóstico das fontes — rode isto primeiro
baixar_informe_fii.py  roda no Brasil: gera o web/public/informe_fii.json
atualizar_fiis.py      gera o web/public/fiis.json
validar_fiis.py        confere o JSON antes de publicar
fiib3/
  config.py            endereços, parâmetros e a tradução papel/tijolo
  cvm_fii.py           informe mensal e cadastro da CVM
  arquivo_informe.py   a ponte para a nuvem: grava e lê o informe_fii.json
  tickers_fii.py       CNPJ <-> código de negociação (B3, com o ISIN de reserva)
  mercado.py           preço, liquidez e a série de rendimentos por cota
  indicadores.py       P/VP, DY, consistência e os filtros de universo
  score.py             score multifator
  pipeline.py          orquestração
  demo.py              dados sintéticos
web/public/fiis.html   a aba
web/public/fiis.js     ranking e simulador, no navegador
web/public/estilo.css  CSS comum às duas telas
```

## Como rodar

No seu computador, no Brasil:

```bash
python verificar_fiis.py        # testa CVM, B3 e Yahoo isoladamente
python atualizar_fiis.py        # baixa tudo e grava web/public/fiis.json
python validar_fiis.py          # confere o resultado
```

Depois é só abrir `web/public/fiis.html` — ou publicar, que a Vercel serve a
pasta inteira.

**No GitHub Actions o caminho é outro**, pela mesma razão do lado das ações: a
CVM recusa conexões de servidores no exterior. Você roda
`python baixar_informe_fii.py` no seu PC uma vez por mês, sobe o
`web/public/informe_fii.json` gerado, e o robô lê esse arquivo em vez de ir à
CVM (`atualizar_fiis.py --informe web/public/informe_fii.json`). Passo a passo
em **`COMO_ATUALIZAR_FIIS.md`**.

O primeiro download leva alguns minutos: o zip do informe mensal tem ~1 MB, mas
o Yahoo é consultado uma vez por fundo para trazer os rendimentos. Fica tudo em
`~/.fiib3_cache`.

## De onde vem cada número

| Dado | Fonte | Defasagem |
|---|---|---|
| Patrimônio, nº de cotas, VP/cota, cotistas | Informe mensal da CVM | até o 15º dia útil do mês seguinte |
| Mandato, segmento de atuação, tipo de gestão | Informe mensal da CVM | idem |
| Razão social e situação cadastral | `cad_fii.csv` da CVM | diária |
| Código de negociação | API da B3; ISIN da CVM como reserva | — |
| Preço e volume | Yahoo Finance | fechamento anterior |
| Rendimentos por cota | Yahoo Finance | data de pagamento |

O informe mensal é o equivalente, em FII, do que a DFP é para as ações — com a
vantagem de ser mensal. É por isso que aqui o problema de defasagem que domina
o lado das ações (balanço de dezembro publicado em março) praticamente não
existe: o pior caso são seis semanas.

## Os indicadores

**P/VP** — preço da cota sobre o valor patrimonial declarado no informe. O
número mais citado e o mais mal usado, porque compara preço com *avaliação
contábil*. Em fundo de tijolo o laudo é anual e defasado; em fundo de papel o
patrimônio é uma carteira de CRI marcada a mercado e o P/VP fica quase colado
em 1. São duas coisas diferentes com o mesmo nome — daí a opção de ranquear as
famílias em separado, ligada por padrão.

**DY 12 meses** — proventos pagos nos últimos 12 meses sobre o preço de hoje.
Convenção de mercado, e o indicador mais fácil de distorcer: um rendimento
extraordinário (venda de imóvel, ganho de capital) infla o número por 12 meses
sem nada de recorrente atrás.

**DY mediano** — mediana dos pagamentos mensais, anualizada. É o que sobra
quando se tira o mês atípico. O score usa o **menor** entre os dois, porque
errar para cima faz alguém comprar contando com uma renda que não existe, e
errar para baixo só deixa o fundo fora de uma lista de triagem.

**Consistência** — metade é ter pago nos 12 meses, metade é ter pago valores
estáveis (1 menos o coeficiente de variação). Doze pagamentos de R$ 0,10 e
cinco pagamentos somando o mesmo total não são a mesma coisa para quem vive de
renda, e o DY sozinho não distingue os dois.

**Liquidez** — volume financeiro médio dos últimos 63 pregões. Em FII isso é
restrição de verdade: boa parte do mercado não negocia R$ 500 mil por dia.

## O score

Cada fator vira um percentil dentro do universo elegível e o score é a média
ponderada desses percentis, de 0 a 100.

Percentil, e não o valor bruto, porque os fatores estão em unidades
incomparáveis e a liquidez, que varia em três ordens de grandeza, dominaria
qualquer soma direta. Percentil, e não a posição no ranking (que é o que
Greenblatt faz do lado das ações), porque a posição descarta a distância: o 1º
e o 2º ficariam sempre igualmente separados, mesmo quando um paga 12% e o outro
8%.

Os pesos padrão — 35% DY, 30% P/VP, 20% consistência, 15% liquidez — são uma
escolha, não um resultado. A tela deixa mexer neles justamente por isso.

**O que o score não olha:** vacância, prazo e tipo dos contratos de locação,
qualidade do inquilino, risco de crédito dos CRI, subordinação, alavancagem,
taxa de administração e de performance, e se o laudo de avaliação reflete
preço de venda hoje. É uma triagem: serve para reduzir 300 fundos a 20 que
merecem leitura de relatório gerencial.

## O que ainda falta

1. **Vacância física e financeira**, do informe trimestral
   (`FII/DOC/INF_TRIMESTRAL`). É o indicador mais relevante que está de fora.
   O arquivo tem uma linha por imóvel e a agregação por fundo dá algum
   trabalho, mas é o próximo passo natural.
2. **Taxa de administração** — está no informe mensal como percentual das
   despesas; falta consolidar em taxa anual sobre o PL.
3. **Rendimentos do FNET** em vez do Yahoo. O comunicado do administrador é a
   fonte oficial e separa rendimento de amortização — que é justamente a
   distinção que o alerta de "DY alto" hoje só consegue estimar.
4. **Backtest do score.** Hoje não existe. Fazê-lo direito exige o informe
   mensal de cada mês do passado (que a CVM tem, ano a ano) e o preço na data —
   e exige respeitar a data de publicação do informe, o mesmo cuidado
   *point-in-time* que o `backtest_historico.py` das ações já toma. Sem isso,
   não há nada dizendo que este score seleciona melhor que ordenar por DY.

## Quando algum indicador aparecer vazio

Quase sempre é a CVM tendo renomeado uma coluna. O código não fixa nome de
coluna nenhum: cada campo é localizado por uma lista de padrões em
`fiib3/cvm_fii.py`. Para ver o que veio de fato no arquivo:

```bash
python verificar_fiis.py --colunas
```

O conserto é acrescentar o nome novo à lista do campo em questão. O
`validar_fiis.py` existe para pegar esse caso antes da publicação: ele falha se
um indicador estiver preenchido em menos de 80% dos fundos, porque uma coluna
renomeada não levanta exceção — ela sai em branco e o arquivo parece bom.

## Aviso

Ferramenta de estudo. Não é recomendação de investimento. O rendimento
distribuído por um fundo imobiliário não é garantido, e rentabilidade passada
não garante rentabilidade futura.
