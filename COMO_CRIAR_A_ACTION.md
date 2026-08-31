# As pastas `.github` e `.streamlit` não sobem para o GitHub

## Primeiro: uma delas você pode esquecer

**`.streamlit` não precisa ir para o GitHub.** Ela só continha ajustes de cor do
app que roda no seu computador. Passei esses ajustes para dentro do
`iniciar.bat`, como opções de linha de comando. Pode apagar a pasta `.streamlit`
sem dó — o projeto não depende mais dela.

Sobra **um único arquivo** para resolver:

```
.github/workflows/atualizar-dados.yml
```

Esse caminho é obrigatório: o GitHub só procura robôs de automação exatamente
nesse lugar. Não dá para renomear a pasta.

## Por que o upload por arrastar não funciona

Não é você. O envio de arquivos pelo navegador do GitHub **descarta, em
silêncio, tudo que começa com ponto**. Ele não avisa, não dá erro — os arquivos
simplesmente não aparecem na lista. É um comportamento conhecido e antigo da
ferramenta.

Ou seja: por mais que você selecione a pasta corretamente, por esse caminho ela
nunca vai subir. Precisa de outra rota.

---

# Rota 1 — Criar o arquivo dentro do GitHub (3 minutos)

Funciona porque aqui você **digita** o caminho em vez de enviá-lo.

### 1. Add file → Create new file

Na página inicial do repositório, o botão **Add file** fica logo à esquerda do
botão verde `Code`. Clique nele e escolha **Create new file**.

### 2. Digite o caminho no campo do nome

No alto da tela aparece um campo com o texto cinza *"Name your file..."*.
Digite ali, com atenção às barras:

```
.github/workflows/atualizar-dados.yml
```

**O que você vai ver acontecer:** ao digitar `.github` e apertar a tecla `/`, o
texto vira uma caixinha cinza escrito `.github` e o cursor pula para um campo
novo. Digite `workflows` e `/` de novo — vira outra caixinha. Aí digite
`atualizar-dados.yml` e pare.

No fim, a linha fica assim:

```
SEU-REPO / .github / workflows /  [atualizar-dados.yml]
```

Se não virou caixinha, é porque você digitou a barra invertida `\` em vez da
barra normal `/`. No teclado ABNT, a barra normal fica na tecla com `?` ao lado
do Shift direito.

### 3. Cole o conteúdo

Abra o arquivo **`atualizar-dados.yml`** que te mandei: clique com o botão
direito → **Abrir com** → **Bloco de Notas**. Ctrl+A para selecionar tudo,
Ctrl+C para copiar.

Volte ao GitHub, clique na área grande de texto abaixo do nome e cole com
Ctrl+V.

> Se aparecerem abas **Edit** e **Preview** no alto, fique na **Edit**.

### 4. Commit

Botão verde **Commit changes** no canto superior direito, e **Commit changes**
de novo na janelinha que abrir.

Pronto. Vá na aba **Actions** e o **Atualizar dados** estará lá.

---

# Rota 2 — GitHub Desktop (recomendada para você)

Vale o investimento de 10 minutos, porque você tem vários repositórios
(`i-finance-lab-gpt`, `bussola-financeira`, `sociedade-malte`...). O GitHub
Desktop resolve o problema das pastas com ponto de uma vez e torna toda
atualização futura um clique, em vez de arrastar arquivos no navegador.

### 1. Instalar

<https://desktop.github.com> → baixe, instale, entre com sua conta do GitHub.

### 2. Trazer o repositório para o PC

**File → Clone repository** → aba **GitHub.com** → escolha `formula-magica` →
escolha uma pasta local → **Clone**.

Isso cria uma pasta vazia (ou com o que já está no GitHub) no seu computador.

### 3. Copiar os arquivos para dentro

Abra a pasta clonada e a pasta do projeto lado a lado no Explorador. Copie
**tudo** do projeto para dentro da pasta clonada, inclusive a `.github`.

> Se a `.github` não aparecer no Explorador: aba **Exibir** → marque
> **Itens ocultos**.

> Não copie a pasta `.venv` se ela existir.

### 4. Enviar

Volte ao GitHub Desktop. Ele lista sozinho tudo que mudou — e desta vez a
`.github` aparece. Escreva uma descrição curta no campo de baixo à esquerda,
clique em **Commit to main**, e depois em **Push origin** no topo.

Daqui em diante, qualquer alteração é: editar o arquivo no PC → abrir o GitHub
Desktop → **Commit** → **Push**.

---

# Rota 3 — Nem precisa do robô

Você pode gerar o arquivo de dados no seu próprio computador e enviar só ele.
O `dados.json` fica em `web/public/`, que é uma pasta normal e sobe por arrastar
sem problema nenhum.

```
.venv\Scripts\python.exe atualizar_dados.py
```

Depois, no GitHub: entre na pasta `web` → `public` → **Add file** →
**Upload files** → arraste o `dados.json` → **Commit changes**.

A Vercel republica em cerca de um minuto.

O robô é conveniência — ele evita que você precise ter o Python rodando para
atualizar. Mas o resultado final é exatamente o mesmo arquivo. **Se essa rota
for confortável, você pode simplesmente nunca criar a Action.**

---

# Conferindo que deu certo

Abra este endereço, trocando pelos seus dados:

```
https://github.com/SEU-USUARIO/SEU-REPO/blob/main/.github/workflows/atualizar-dados.yml
```

Se o arquivo aparecer, está resolvido. Vá na aba **Actions**, clique em
**Atualizar dados** na coluna da esquerda, e use o botão **Run workflow** à
direita.

Depois de rodar, no log do passo **Conferir o resultado** você deve ver algo como:

```
empresas: 80 | com preço: 74 | gerado em 2026-08-31 19:12
```

E no site, o aviso *"⚠ dados sintéticos de demonstração"* desaparece.

---

# Se ainda não aparecer na aba Actions

**O arquivo está no branch `main`?**
O botão *Run workflow* só aparece para workflows no branch padrão.

**A aba Actions existe?**
Se nem a aba aparece: **Settings → Actions → General → Actions permissions** →
**Allow all actions and reusable workflows** → **Save**.

**A indentação sobreviveu à cópia?**
YAML é sensível a espaços. Se o GitHub mostrar um aviso vermelho no arquivo,
recopie do Bloco de Notas — nunca do Word, que troca espaços e aspas.
