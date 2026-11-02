# Aba Oportunidades

Ações com o P/VP muito abaixo da própria história. Página
`web/public/oportunidades.html`; a conta está em
`web/public/oportunidades_motor.js` e, igual, em `mercado/oportunidades.py`
(a referência, usada pelos testes e por `listar_oportunidades.py`).

## A regra

Para cada papel do `pvp_papeis.json` (P/VP semanal desde 2015, patrimônio dos
controladores, balanço já entregue à CVM em cada data) e cada janela de 1, 5 ou
10 anos terminando hoje:

    z = (ln P/VP hoje − média do ln P/VP na janela) / desvio do ln P/VP na janela

O papel entra na lista quando `z < −k` (k = 2 por padrão; a tela oferece 1,5,
2, 2,5 e 3). "Quase lá" é `−k ≤ z < −k + 0,5`.

- **P/VP-gatilho** = `exp(média − k × desvio)`: o P/VP em que o papel entra.
- **Preço-gatilho** = P/VP-gatilho × patrimônio por ação guardado.
- **Percentil** = % das semanas da janela com P/VP abaixo do de hoje.
- **Desde** = início da sequência atual de semanas abaixo do gatilho, cada uma
  medida com a janela que terminava nela (sem olhar o futuro).

### Por que o logaritmo

O P/VP não fica negativo e tem cauda longa para cima. Na escala normal, "média
− 2 desvios" é negativo em boa parte dos papéis, e a regra nunca dispara.

### Escolhas

| tema | escolha |
|---|---|
| janela | datas > hoje − N anos e ≤ hoje; inclui hoje |
| desvio | amostral (n − 1) |
| cobertura | ≥ 80% das semanas da janela com P/VP, e ≥ 26 semanas; a grade tem que alcançar o início da janela |
| ponto de hoje | último fechamento do `dados.json` ÷ VPA guardado; mesma semana (ou mesmo dia) do último ponto substitui, semana nova acrescenta |
| data do preço | `geradoEm` antes do meio-dia = dia útil anterior (a coleta roda de madrugada) |
| janela padrão | 5 anos (1 ano dispara com quedas comuns; 10 anos mistura regimes) |
| estado | no link: `#j=5&k=2&todas=1&salto=1` |

### Salto de patrimônio

Se dentro da janela o **patrimônio por ação** mudou 50% ou mais de um balanço
para o outro, a média mistura duas empresas — sobretudo porque o histórico usa
o nº de ações de hoje no passado, e um aumento de capital vira degrau. O papel
sai da lista principal e aparece em "Fora da lista por salto", com o degrau. Um
botão traz de volta. **Queda de preço nunca é salto**: é o que a aba procura.

Os degraus vêm do campo `v` de cada papel no `pvp_papeis.json`
(`[[índice da data, VPA], ...]`, gravado por `pvp_papeis.degraus_vpa`). O
arquivo publicado em 02/11/2026 ainda não tem esse campo; até ele ser refeito
com `pvp_papeis.bat`, vale a regra de reserva: P/VP que dobrou ou caiu à metade
em uma semana, **exceto** depois de data do último balanço + 46 dias, quando o
patrimônio já não muda e todo movimento é de preço.

## O que não muda

Nenhum robô novo. O `atualizar-dados.yml` já grava o ponto semanal do
`pvp_papeis.json` toda sexta, e o `dados.json` traz o preço do dia. Balanço
novo entra quando o histórico é refeito no computador (`pvp_papeis.bat`),
depois de cada temporada de ITR/DFP — a tela avisa quando o patrimônio mais
comum tem mais de 185 dias.

## Conferir sem abrir o site

    python listar_oportunidades.py --janela 5 --k 2

## Testes

`tests/test_oportunidades.py`: a conta contra `statistics`, o gatilho, a razão
do log, cobertura, grade curta, ponto de hoje, data do preço, saltos de
patrimônio e de preço, "desde" sem olhar o futuro, e a paridade com o motor JS
(`tests/paridade_oportunidades.mjs`) em arquivo sintético e nos arquivos
publicados. Nenhum acessa a rede.
