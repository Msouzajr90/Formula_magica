# Guia: rodar e publicar

Escrito para Windows, e para quem nunca usou Streamlit.

O projeto agora tem **duas frentes**, que compartilham o mesmo motor de cálculo
em Python:

| | Site na Vercel | Streamlit no seu PC |
|---|---|---|
| Para quê | vitrine pública, consulta rápida, compartilhar | análise pesada, backtest, ajuste fino |
| Onde roda | GitHub + Vercel, como seus outros projetos | seu computador |
| Velocidade | abre na hora | 5 a 15 min na primeira carga |
| Dados | arquivo gerado por você, com data visível | busca ao vivo |
| Fronteira eficiente | recalculada no navegador | recalculada em Python |
| Backtest histórico | não | sim |
| Trocar EY / ROIC de método | não | sim |

---

# Parte 1 — Por que a Vercel não roda o Streamlit

Vale entender, porque explica o desenho da solução.

O Streamlit é um **processo que fica ligado**. Ele mantém uma conexão WebSocket
aberta com cada visitante e guarda o estado da sessão na memória do servidor.
Quando você mexe num controle, o servidor recalcula e empurra a tela nova pela
conexão.

A Vercel não hospeda processos ligados. Ela é feita para **funções que nascem,
respondem e morrem**, com limite de duração e sem memória entre chamadas. É o
que faz ela ser rápida e gratuita — e é justamente o que o Streamlit não tolera.
Não é configuração faltando; são modelos de execução diferentes.

E tem um segundo problema, independente do primeiro: baixar e processar os
arquivos da CVM leva minutos e centenas de MB. Isso não cabe numa função
serverless de jeito nenhum.

**A solução usa cada peça no que ela é boa:**

```
   VOCÊ                GITHUB ACTIONS              GITHUB              VERCEL
 "Run workflow"  →   roda o Python           →   commit do      →   publica o
                     (16 GB RAM, sem          dados.json           site estático
                      limite de tempo)                                   ↓
                     CVM + B3 + Yahoo                              visitante abre
                            ↓                                       e o navegador
                     dados.json (~150 KB)                          faz as contas
```

O site que a Vercel serve é HTML, CSS e JavaScript puros — sem framework, sem
dependências, sem build. Ele lê o `dados.json` e **refaz o ranking e a
otimização de Markowitz no próprio navegador**. Então mexer no número de ações,
no peso máximo ou no perfil de risco responde instantaneamente, sem ida ao
servidor.

> O otimizador em JavaScript foi conferido contra o de Python: nos mesmos dados,
> os pesos batem até a sexta casa decimal. É gradiente projetado com projeção no
> simplex limitado, resolvendo o mesmo problema.

---

# Parte 2 — Publicar na Vercel

Você já faz isso no `i-finance-lab-gpt` e no `bussola-financeira`. O fluxo é o
mesmo; só há um passo a mais, que é rodar a ação de atualização.

## 2.1 Subir para o GitHub

1. No GitHub: **+** → **New repository** → nome `formula-magica` → **Create**.
2. Na página que abrir, clique em **uploading an existing file**.
3. Abra a pasta do projeto, selecione tudo (Ctrl+A) e arraste para o navegador.

   > Não suba a pasta `.venv` se ela existir — são milhares de arquivos e não
   > serve para nada no repositório.

   > A pasta `.github` é oculta no Windows. Ative **Exibir → Itens ocultos** no
   > Explorador de Arquivos antes de selecionar, senão o robô de atualização não
   > vai junto.

4. **Commit changes**.

## 2.2 Conectar na Vercel

1. <https://vercel.com/new>
2. Escolha o repositório `formula-magica` → **Import**.
3. **Não mexa em nada** nas configurações de build. O arquivo `vercel.json` já
   diz o que é preciso:
   - Framework: nenhum
   - Build Command: nenhum
   - Output Directory: `web/public`
4. **Deploy**.

Em menos de um minuto o site está no ar. Como não há build, é praticamente
instantâneo.

Na primeira visita ele já mostra algo: o repositório vem com um `dados.json` de
demonstração, com dados sintéticos. O site avisa isso em cima, ao lado da data.

## 2.3 Gerar os dados de verdade

1. No repositório do GitHub, aba **Actions**.
2. Na coluna da esquerda, **Atualizar dados**.
3. Botão **Run workflow** à direita. Pode ajustar a liquidez mínima e quantas
   empresas exportar, ou deixar como está.
4. **Run workflow** de novo, para confirmar.

O robô então:

- instala o Python e as bibliotecas;
- roda o `verificar_dados.py` e mostra o resultado no log;
- roda os 28 testes;
- baixa CVM, B3 e Yahoo e gera o `dados.json`;
- **confere se o resultado faz sentido** — se vierem menos de 15 empresas, ou se
  o arquivo sair em modo demonstração, ele aborta e **não** sobrescreve o
  arquivo bom;
- faz o commit.

A Vercel percebe o commit e republica sozinha. Leva de 5 a 15 minutos no total,
quase tudo baixando da CVM. Da segunda vez em diante o cache do GitHub Actions
corta isso bastante.

Se algo falhar, clique no job vermelho e leia o log — o `verificar_dados.py`
aparece logo no começo e quase sempre aponta a causa.

## 2.4 Custo

Tudo dentro do gratuito. GitHub Actions dá 2.000 minutos por mês em repositório
privado (e é ilimitado em repositório público); cada atualização gasta de 5 a 15.
A Vercel serve arquivo estático, que é o caso mais barato que existe para ela.

## 2.5 Domínio próprio

No painel da Vercel: **Settings → Domains → Add**. Igual aos seus outros
projetos.

---

# Parte 3 — Rodar o Streamlit no seu PC

Aqui fica o que o site estático não faz: backtest histórico, trocar o método de
cálculo do EY e do ROIC, escolher o estimador de covariância, exportar a
planilha completa.

## 3.1 Instalar o Python

1. <https://www.python.org/downloads/> → baixe o instalador do Windows.
2. **Na primeira tela, marque "Add python.exe to PATH"** antes de clicar em
   *Install Now*. É o erro nº 1 de quem está começando.
3. Confirme abrindo o Prompt de Comando (tecla Windows, digite `cmd`):

   ```
   python --version
   ```

## 3.2 Abrir

**Duplo clique em `iniciar.bat`.** Na primeira vez ele cria o ambiente, instala
as bibliotecas, roda a verificação das fontes de dados e abre no navegador.
Depois disso abre em segundos.

> Se aparecer "O Windows protegeu o computador", clique em **Mais informações**
> → **Executar assim mesmo**. É só porque o arquivo veio da internet.

## 3.3 Backtest histórico

Este é o teste honesto da estratégia — reconstrói o ranking em cada data usando
só o que já estava publicado na época:

```
.venv\Scripts\python.exe backtest_historico.py --inicio 2018 --fim 2025 --n 30
```

Para comparar com o método original do TCC e medir quanto do desempenho vinha
dos vieses:

```
.venv\Scripts\python.exe backtest_historico.py --inicio 2018 --fim 2025 ^
    --ey lpa_original_tcc --roic ativo_total --peso-max 1.0 --custo-bps 0
```

---

# Parte 4 — A verificação das fontes de dados

Preciso repetir isto, porque é a limitação mais importante do que te entreguei:
**eu não consegui testar o download real.** O ambiente onde escrevi o código está
com a rede bloqueada. Validei a matemática (28 testes automáticos), conferi o
otimizador de JavaScript contra o de Python e cliquei pelas duas interfaces — mas
com dados sintéticos. As conexões com CVM, B3 e Yahoo nunca rodaram de verdade.

O `verificar_dados.py` existe para fechar essa lacuna. Roda automaticamente no
`iniciar.bat` e no GitHub Actions, e a qualquer momento:

```
.venv\Scripts\python.exe verificar_dados.py --completo
```

| # | Verificação | Se falhar |
|---|---|---|
| 1–2 | Bibliotecas, internet | nada roda |
| 3–4 | Portal da CVM, estrutura do zip | sem demonstrações financeiras |
| 5 | Códigos de conta (EBIT, balanço) | o plano de contas mudou |
| 6 | ITR trimestral | perde os 12 meses móveis |
| 7 | Data de entrega (`DT_RECEB`) | backtest usa aproximação de +90 dias |
| 8 | Cadastro e setor | filtro setorial para de funcionar |
| 9 | API de companhias da B3 | sem mapeamento CNPJ ↔ ticker |
| 10–11 | Cotações, volume financeiro | sem preços / sem filtro de liquidez |
| 12 | Número de ações | **EV não pode ser calculado** — o mais frágil |

Os dois que eu apostaria que quebram primeiro são o **9** (a API da B3 é um
endpoint interno do site deles, sem contrato público) e o **12** (o `yfinance`
troca os nomes dos campos com frequência). Se algum falhar, me manda a saída
inteira — cada caso tem conserto.

---

# Parte 5 — Problemas comuns

**Na Vercel: "404 NOT_FOUND" ou página em branco**
O Output Directory não ficou como `web/public`. Confira em **Settings → General**
e faça **Redeploy**.

**O site diz "Não foi possível carregar os dados"**
O `dados.json` não está publicado. Rode a ação **Atualizar dados** no GitHub.

**O site mostra "⚠ dados sintéticos de demonstração"**
É o arquivo de exemplo que veio no repositório. Rode a ação para gerar os reais.

**Mudei os dados mas o site mostra os antigos**
O `vercel.json` já manda não cachear o `dados.json`, e o site adiciona um número
aleatório na URL. Se ainda assim persistir, Ctrl+Shift+R no navegador.

**A ação do GitHub falha em "Conferir o resultado"**
É proteção funcionando: vieram poucas empresas, então ele preferiu não
sobrescrever o arquivo bom. Abra o log do passo "Verificar as fontes de dados"
para ver qual fonte quebrou.

**"python não é reconhecido como um comando"**
O PATH não foi marcado na instalação. Reinstale marcando *Add python.exe to PATH*.

**"Port 8501 is already in use"**
Já tem uma instância aberta. Feche a outra janela preta, ou rode
`.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502`.

**Ranking vazio ou com pouquíssimas empresas**
Filtros apertados demais. Baixe a liquidez mínima. A aba **Excluídas** mostra
exatamente onde cada empresa caiu.

**Números estranhos em uma empresa específica**
Provavelmente o número de ações do Yahoo para empresa com duas classes (ON e PN).
Está na seção 3.5 da `AUDITORIA.md`. Confira o valor de mercado no site de RI.
