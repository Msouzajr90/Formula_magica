# Fórmula Mágica B3

Plataforma para montar carteiras de ações da B3 combinando o **ranking de
Greenblatt** (ROIC + Earnings Yield) com o **modelo de Markowitz** de
média-variância.

Reescrita do algoritmo do TCC *"Montagem de carteira de ações a partir do ranking
de Greenblatt e do modelo de Markowitz"* (Marco Antonio Alves de Souza Junior,
MBA em Data Science e Analytics, 2023), com correções de metodologia e de
implementação — ver `AUDITORIA.md`.

---

Há duas formas de usar, com o mesmo motor de cálculo por trás:

- **Site estático** (`web/public/`), publicado no GitHub + Vercel. Abre na hora,
  refaz ranking e Markowitz no navegador. Os dados vêm de um `dados.json`
  gerado sob demanda por um GitHub Action.
- **App Streamlit** (`app.py`), rodando no seu computador. Busca os dados ao
  vivo e faz o que o site não faz: backtest histórico, troca do método de
  cálculo dos indicadores, exportação para Excel.

Passo a passo dos dois, incluindo publicação: **`GUIA_PUBLICACAO.md`**.

O site tem uma segunda aba, de **fundos imobiliários**: informe mensal da CVM
cruzado com preço e rendimentos, ranking por DY, P/VP, consistência do
rendimento e liquidez, e um simulador em que você escolhe os fundos. Roda pelo
mesmo caminho (`python atualizar_fiis.py` gera o `web/public/fiis.json`) e com a
mesma divisão Brasil/nuvem das ações — `baixar_informe_fii.py` no seu PC,
o robô lendo o arquivo. Documentada em **`FIIS.md`** e em
**`COMO_ATUALIZAR_FIIS.md`**.

## Começar (Windows)

Dê **duplo clique em `iniciar.bat`**. Na primeira vez ele instala tudo, roda a
verificação das fontes de dados e abre a plataforma no navegador.

## Começar (linha de comando)

Precisa de Python 3.10 ou mais novo.

```bash
cd formula-magica
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python verificar_dados.py        # testa CVM, B3 e Yahoo — rode isto primeiro
streamlit run app.py
```

O navegador abre em `http://localhost:8501`.

## Verificação das fontes de dados

As APIs da CVM, da B3 e do Yahoo mudam sem aviso. `verificar_dados.py` testa
cada conexão isoladamente e diz qual quebrou e o que isso afeta:

```bash
python verificar_dados.py              # rápido
python verificar_dados.py --completo   # inclui um teste ponta a ponta
```

Rode-o sempre que algo parar de funcionar — ele isola a causa em quase todos
os casos.

Na primeira execução com dados reais, o download dos arquivos da CVM leva de
5 a 15 minutos (são ~200 MB por ano de DFP + ITR). Tudo fica em cache em
`~/.magicb3_cache`, e as execuções seguintes levam segundos. Use o botão
**Limpar cache de dados** quando quiser forçar a atualização — o recomendado é
uma vez por trimestre, depois da temporada de balanços.

Para conhecer a interface sem esperar nada, escolha **Demonstração (offline)**
na barra lateral: os dados são sintéticos e servem só para navegar.

### Publicar na internet (opcional, gratuito)

1. Suba a pasta num repositório do GitHub.
2. Em <https://share.streamlit.io>, conecte o repositório e aponte para `app.py`.

Fica acessível de qualquer navegador, inclusive do celular.

## Backtest honesto

O backtest da interface aplica *a carteira de hoje* ao passado — serve para ver
o comportamento dos papéis, não para validar a estratégia. A validação de
verdade reconstrói o ranking em cada data:

```bash
python backtest_historico.py --inicio 2018 --fim 2025 --n 30
```

Ele usa apenas demonstrações já entregues à CVM em cada data (coluna
`DT_RECEB`), recalcula a liquidez com a janela anterior à compra e desconta
custo de transação. Compare com a versão original do TCC:

```bash
python backtest_historico.py --inicio 2018 --fim 2025 \
    --ey lpa_original_tcc --roic ativo_total --peso-max 1.0 --custo-bps 0
```

## Testes

```bash
python -m pytest tests -q
```

---

## Estrutura

```
iniciar.bat               duplo clique no Windows: instala, verifica e abre
app.py                    interface Streamlit (roda local)
verificar_dados.py        diagnóstico das fontes de dados
atualizar_dados.py        gera o web/public/dados.json para o site
backtest_historico.py     backtest point-in-time (linha de comando)
baixar_informe_fii.py     roda no Brasil: gera o web/public/informe_fii.json
verificar_fiis.py         diagnóstico das fontes de FII
atualizar_fiis.py         gera o web/public/fiis.json (ver FIIS.md)
validar_fiis.py           confere o fiis.json antes de publicar
vercel.json               configuração do site estático
web/public/               site publicado na Vercel (HTML + CSS + JS puros)
.github/workflows/        robô que atualiza os dados sob demanda
fiib3/                    fundos imobiliários — ver FIIS.md
magicb3/
  config.py               parâmetros e códigos de conta da CVM
  cvm.py                  download e normalização de DFP/ITR, EBIT LTM
  tickers.py              mapeamento CD_CVM <-> ticker da B3
  prices.py               cotações, liquidez e valor de mercado (Yahoo)
  fundamentals.py         ROIC, EV, Earnings Yield e filtros
  ranking.py              ranking combinado de Greenblatt
  optimizer.py            Markowitz com Ledoit-Wolf e restrição de peso
  backtest.py             retorno de carteira, métricas de risco
  pipeline.py             orquestração
  report.py               exportação Excel
  demo.py                 dados sintéticos para o modo demonstração
tests/                    107 testes, rodam sem rede
```

## Fontes de dados

| Dado | Fonte | Observação |
|---|---|---|
| DRE e Balanço | `dados.cvm.gov.br` (DFP anual + ITR trimestral) | oficial, gratuito |
| Cadastro e setor | `cad_cia_aberta.csv` da CVM | usado para excluir setores |
| CNPJ ↔ ticker | API de companhias listadas da B3 | traz o `codeCVM` |
| Cotações e volume | Yahoo Finance (`yfinance`) | fechamento ajustado |
| Nº de ações | Yahoo Finance | ver limitação em `AUDITORIA.md` |

## Aviso

Ferramenta de estudo e pesquisa. Não é recomendação de investimento.
Rentabilidade passada não garante rentabilidade futura.
