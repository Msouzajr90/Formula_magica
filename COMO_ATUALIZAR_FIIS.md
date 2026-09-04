# Publicar e atualizar a aba de FIIs

A mesma restrição do lado das ações vale aqui, e por isso o desenho é o mesmo.
Vale reler o `COMO_ATUALIZAR.md`: o diagnóstico que está lá — a CVM não fala com
os servidores do GitHub — se aplica igual ao informe mensal de FII.

```
  SEU PC (Brasil)                    GITHUB                      VERCEL
  ───────────────                    ──────                      ──────
  baixar_informe_fii.py
     ↓ acessa a CVM
  informe_fii.json  ──── você sobe ──→  fica no repositório
     (~250 KB)                              ↓
                                     robô lê o arquivo
                                     + preços e proventos no Yahoo
                                     + códigos dos FII na B3
                                            ↓
                                        fiis.json  ────────────→  site
                                                                publicado
```

| O quê | Onde roda | Com que frequência |
|---|---|---|
| `baixar_informe_fii.py` | seu PC, no Brasil | uma vez por mês, depois do dia 20 |
| Ação "Atualizar FIIs" | GitHub | quando você quiser |

Por que uma vez por mês e não por trimestre: o informe de FII é mensal, e é dele
que sai o valor patrimonial por cota — o denominador do P/VP. Se atrasar não
quebra nada, só envelhece o P/VP; o robô avisa quando o arquivo passa de 45 dias
e o site mostra em qual competência ele está.

---

## Primeira vez — colocar os arquivos no repositório

Se você já usa o **GitHub Desktop** (Rota 2 do `COMO_CRIAR_A_ACTION.md`), é só
copiar os arquivos novos para dentro da pasta clonada, **Commit to main** e
**Push origin**. Pule para a seção seguinte.

Se ainda não usa, vale instalar agora — são cinco arquivos novos em pastas
diferentes, e um deles está dentro da `.github`, que **o upload pelo navegador
descarta em silêncio** (é o problema descrito no `COMO_CRIAR_A_ACTION.md`).

O que precisa ir para o repositório:

```
fiib3/                              pasta nova, 10 arquivos
baixar_informe_fii.py               roda no seu PC
atualizar_fiis.py                   roda no robô
verificar_fiis.py                   diagnóstico
validar_fiis.py                     confere antes de publicar
tests/test_fiis.py                  testes
tests/paridade_score.mjs            teste do score no navegador
web/public/fiis.html                a aba
web/public/fiis.js                  a aba
web/public/estilo.css               CSS agora comum às duas telas
web/public/index.html               alterado: nav e link para o CSS
vercel.json                         alterado: cache dos arquivos novos
.github/workflows/atualizar-fiis.yml   o robô  ← este é o que não sobe arrastando
FIIS.md, COMO_ATUALIZAR_FIIS.md     documentação
README.md                           alterado
```

Se preferir não instalar nada, o `.yml` pode ser criado **digitando o caminho**
dentro do GitHub — é a Rota 1 do `COMO_CRIAR_A_ACTION.md`, funciona porque ali
você digita `.github/workflows/atualizar-fiis.yml` em vez de arrastar a pasta.
O resto sobe arrastando normalmente.

> Atenção a um detalhe: o `index.html` deixou de ter o CSS dentro dele e passou
> a carregar `estilo.css`. Se você subir o `index.html` novo sem o `estilo.css`,
> a página das ações fica sem estilo nenhum. Os dois andam juntos.

---

## Toda vez — o ciclo de atualização

### 1. No seu PC, uma vez por mês

```
.venv\Scripts\python.exe baixar_informe_fii.py
```

Ele testa a rota até a CVM, baixa o zip do informe mensal (~1 MB), lê as três
últimas competências, junta com o cadastro de fundos e grava
`web\public\informe_fii.json`. Leva menos de um minuto.

Ao terminar, imprime algo assim:

```
  1.247 fundos | competencia 2026-08
  [ok   ] patrimonio liquido            : 1.240 preenchidos
  [ok   ] valor patrimonial por cota    : 1.238 preenchidos
  [ok   ] numero de cotas               : 1.244 preenchidos
  [ok   ] codigo ISIN                   : 1.180 preenchidos
  Gravado em web\public\informe_fii.json
  1.247 fundos | 243 KB | competencia 2026-08
```

**Se aparecer `FALHA` em alguma linha**, a CVM renomeou a coluna. Rode:

```
.venv\Scripts\python.exe verificar_fiis.py --colunas
```

Ele despeja os nomes reais das colunas do CSV. O conserto é acrescentar o nome
novo à lista daquele campo em `fiib3/cvm_fii.py` — o código procura por padrões,
não por nome exato, então basta uma linha.

### 2. Subir o arquivo

`web` → `public` → **Add file** → **Upload files** → arraste o
`informe_fii.json` → **Commit changes**. Pasta comum, arquivo comum: sobe
arrastando, sem o problema das pastas com ponto.

Pelo GitHub Desktop é **Commit to main** → **Push origin**, como sempre.

### 3. Rodar o robô

Aba **Actions** → **Atualizar FIIs** (coluna da esquerda) → botão **Run
workflow** → **Run workflow**.

Ele faz, nesta ordem:

1. confere que o `informe_fii.json` existe e mostra a competência e a idade —
   se o arquivo não estiver lá, **para aqui** com uma mensagem dizendo o que
   fazer, em vez de tentar a CVM e falhar 20 minutos depois num timeout;
2. roda o `verificar_fiis.py` (informativo, não derruba a execução);
3. roda os 107 testes;
4. gera o `fiis.json` lendo o arquivo + Yahoo + B3;
5. roda o `validar_fiis.py` — e **se algum indicador vier vazio em mais de 20%
   dos fundos, ele falha e não publica**, deixando no ar o arquivo bom do dia
   anterior;
6. commita o `fiis.json`, e a Vercel republica em cerca de um minuto.

No log do passo **Conferir o resultado** você deve ver algo como:

```
competencia        : 2026-08
elegiveis          : 214
  P/VP            :  99.5% preenchido
  dividend yield  :  98.6% preenchido
OK: dados validos, pode publicar.
```

E no site, o aviso vermelho *"⚠ dados sintéticos de demonstração"* desaparece.

O robô também roda sozinho de segunda a sexta, às 20h30 de Brasília (meia hora
depois do de ações, para os dois não brigarem pelo push). Ele usa sempre o
último `informe_fii.json` que você subiu — os preços e os rendimentos ficam
atualizados todo dia sem você fazer nada; só o informe depende de você.

---

## Se preferir não usar o robô

Com o Python instalado, dá para pular o GitHub Actions inteiro. No seu PC:

```
.venv\Scripts\python.exe baixar_informe_fii.py
.venv\Scripts\python.exe atualizar_fiis.py --informe web/public/informe_fii.json
.venv\Scripts\python.exe validar_fiis.py
```

E suba o `fiis.json` pelo navegador. A Vercel republica em um minuto.

Rodando no seu PC você nem precisa do `--informe`: sem ele, o
`atualizar_fiis.py` vai direto à CVM, que responde normalmente do Brasil. O
arquivo intermediário existe só por causa do robô.

---

## Quando alguma coisa der errado

**O robô para no primeiro passo dizendo que o `informe_fii.json` não existe.**
É o comportamento correto: você ainda não subiu o arquivo, ou subiu na pasta
errada. Ele tem que estar em `web/public/informe_fii.json`.

**O `validar_fiis.py` falha dizendo que um indicador está vazio.**
Quase sempre é coluna renomeada pela CVM, e o arquivo que você gerou no PC já
saiu com o problema — o `baixar_informe_fii.py` teria mostrado um `FALHA` na
tela. Rode `verificar_fiis.py --colunas` e conserte `fiib3/cvm_fii.py`.

**Poucos fundos no ranking.**
Olhe a aba **Excluídos** do site: cada fundo cortado aparece lá com o motivo.
Se a maioria estiver como "sem cotação no Yahoo", o problema é o mapa de
códigos; se estiver como "liquidez abaixo de...", é só afrouxar o filtro na
própria tela ou passar `--liquidez 200000` ao gerar.

**A aba Actions não mostra "Atualizar FIIs".**
O `.yml` não subiu — é o problema das pastas com ponto. Confira abrindo
`https://github.com/Msouzajr90/Formula_magica/blob/main/.github/workflows/atualizar-fiis.yml`.

**A tela das ações ficou sem formatação.**
Faltou subir o `web/public/estilo.css` junto com o `index.html` novo.
