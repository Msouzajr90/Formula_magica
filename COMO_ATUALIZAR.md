# A CVM bloqueia servidores estrangeiros — como o sistema ficou

## O que o diagnóstico provou

```
host        : dados.cvm.gov.br
IPv4        : FALHA — 45.7.170.66: TimeoutError timed out
IPv6        : FALHA — 2804:3e68:170::66: [Errno 101] Network is unreachable
veredito    : nenhum dos dois conecta
```

Duas coisas diferentes acontecendo, e as duas condenam a mesma ideia:

- **IPv6** não tem rota a partir dos servidores do GitHub. Isso sozinho eu
  corrigi forçando IPv4.
- **IPv4 expira.** Não é "conexão recusada", é silêncio: os pacotes saem e nada
  volta. Essa é a assinatura de um firewall descartando tráfego — no caso, o da
  CVM descartando IPs de fora do Brasil.

O segundo ponto não tem conserto no código. Os servidores do GitHub Actions
ficam nos Estados Unidos, e a CVM não fala com eles. Ponto.

Confirmação de que o problema é geográfico e não do projeto: **Yahoo Finance e a
API da B3 funcionaram perfeitamente** do mesmo servidor, no mesmo instante —
cotações do pregão, volume financeiro, número de ações, 3.306 emissores da B3.
Só a CVM recusa.

## A nova arquitetura

Separei o que muda devagar do que muda todo dia:

```
  SEU PC (Brasil)                    GITHUB                      VERCEL
  ───────────────                    ──────                      ──────
  baixar_fundamentos.py
     ↓ acessa a CVM
  fundamentos.json  ──── você sobe ──→  fica no repositório
     (~200 KB)                              ↓
                                     robô lê o arquivo
                                     + busca preços no Yahoo
                                     + lista de tickers na B3
                                            ↓
                                       dados.json  ────────────→  site
                                                                publicado
```

Balanços mudam **quatro vezes por ano**. Preços mudam todo dia. Então:

| O quê | Onde roda | Com que frequência |
|---|---|---|
| `baixar_fundamentos.py` | seu PC, no Brasil | uma vez por trimestre |
| Ação "Atualizar dados" | GitHub | quando você quiser |

Isso não é uma gambiarra: é o desenho correto para a restrição real. Você não
precisa manter o computador ligado, nem rodar nada no dia a dia.

## O que muda para você

Agora o Python **precisa** ser instalado, mas só para a tarefa trimestral.

### Uma vez: instalar o Python

1. <https://www.python.org/downloads/>
2. **Marque "Add python.exe to PATH"** na primeira tela do instalador.
3. Descompacte o projeto e dê **duplo clique em `iniciar.bat`** — ele monta o
   ambiente sozinho. Pode fechar quando abrir o navegador.

### Uma vez por trimestre: gerar os fundamentos

No Prompt de Comando, dentro da pasta do projeto:

```
.venv\Scripts\python.exe baixar_fundamentos.py
```

Ele testa a rota até a CVM, baixa DFP e ITR dos três últimos anos, calcula o
EBIT de 12 meses móveis e grava `web\public\fundamentos.json`. Demora de 5 a 15
minutos na primeira vez.

Ao terminar, imprime algo como:

```
  Gravado em web\public\fundamentos.json
  712 empresas | 198 KB
  489 com 12 meses móveis (DFP+ITR); 223 só com o anual
```

### Subir o arquivo

No GitHub, entre em `web` → `public` → **Add file** → **Upload files** →
arraste o `fundamentos.json` → **Commit changes**.

Pasta comum, arquivo comum: sobe arrastando, sem o problema das pastas com
ponto.

### Rodar o robô

Aba **Actions** → **Atualizar dados** → **Run workflow**.

Agora ele passa. Não fala mais com a CVM — lê o arquivo que você subiu e só
busca preços no Yahoo e a lista de tickers na B3, que funcionam de lá.

**Quando repetir:** depois de cada temporada de balanços — março, maio, agosto e
novembro. Se passarem 120 dias, o próprio sistema avisa que o arquivo envelheceu.

## O que mudou no código

| Arquivo | O que faz |
|---|---|
| `baixar_fundamentos.py` | **novo** — roda no Brasil, gera o `fundamentos.json` |
| `magicb3/arquivo_fundamentos.py` | **novo** — grava e lê esse arquivo |
| `magicb3/rede.py` | **novo** — força IPv4 e diagnostica IPv4 vs IPv6 |
| `magicb3/pipeline.py` | aceita o arquivo e pula a CVM quando ele existe |
| `atualizar_dados.py` | novo parâmetro `--fundamentos` |
| `verificar_dados.py` | checa o arquivo; para de insistir na CVM em 30s |
| `.github/workflows/` | passa `--fundamentos web/public/fundamentos.json` |
| `magicb3/tickers.py` | filtra BDRs — a B3 devolvia 3.306 emissores |

São 30 testes automáticos, incluindo um que exporta e reimporta o arquivo de
fundamentos e confere que os números batem na volta.

## Se preferir não usar o robô

Com o Python instalado, dá para pular o GitHub Actions inteiro:

```
.venv\Scripts\python.exe baixar_fundamentos.py
.venv\Scripts\python.exe atualizar_dados.py --fundamentos web/public/fundamentos.json
```

Depois suba o `dados.json` pelo navegador. A Vercel republica em um minuto.

O robô economiza esse segundo comando — útil para atualizar preços sem ligar o
computador. Mas é conveniência, não necessidade.

## E o app Streamlit?

Continua funcionando e agora faz sentido usá-lo: rodando no seu PC, ele acessa
a CVM direto, sem precisar de arquivo nenhum. É lá que ficam o backtest
histórico, a troca do método de cálculo do EY e do ROIC, e a exportação para
Excel.

```
iniciar.bat
```
