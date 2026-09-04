/* =============================================================================
 * Aba de fundos imobiliários.
 *
 * O arquivo `fiis.json` traz os indicadores já tratados, um por fundo. Tudo o
 * que depende de escolha do usuário — pesos dos fatores, filtros, quais fundos
 * entram e como o capital se divide — é calculado aqui, no navegador, para que
 * mexer num controle responda na hora e não dependa de servidor nenhum.
 *
 * O score implementado aqui precisa dar o mesmo resultado que `fiib3/score.py`.
 * `tests/test_fiis.py` roda os dois em cima dos mesmos números e compara.
 * =========================================================================== */

// ===========================================================================
// Formatação
// ===========================================================================
const nf = (d = 1) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1) => (v == null || !isFinite(v)) ? '—' : nf(d).format(v * 100) + '%';
const brl = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : 'R$ ' + nf(d).format(v);
const num = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : nf(d).format(v);
function compacto(v) {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return 'R$ ' + nf(1).format(v / 1e9) + ' bi';
  if (a >= 1e6) return 'R$ ' + nf(0).format(v / 1e6) + ' mi';
  if (a >= 1e3) return 'R$ ' + nf(0).format(v / 1e3) + ' mil';
  return brl(v, 0);
}
const el = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ===========================================================================
// Motor do score — espelho de fiib3/score.py
// ===========================================================================
/** Percentil em [0,1] com média nos empates; ausente vira 0,5.
 *  Equivale a `Series.rank(method='average', pct=True)` do pandas. */
function percentil(valores, maiorMelhor = true) {
  const n = valores.length;
  const out = new Array(n).fill(0.5);
  const idx = [];
  for (let i = 0; i < n; i++) {
    const v = valores[i];
    if (v != null && isFinite(v)) idx.push(i);
  }
  if (idx.length <= 1) return out;

  idx.sort((a, b) => valores[a] - valores[b]);
  const total = idx.length;
  let i = 0;
  while (i < total) {
    let j = i;
    while (j + 1 < total && valores[idx[j + 1]] === valores[idx[i]]) j++;
    // posições 1-based de i..j; a média delas é o rank do grupo empatado
    const rank = (i + 1 + j + 1) / 2;
    const p = rank / total;
    for (let k = i; k <= j; k++) out[idx[k]] = maiorMelhor ? p : 1 - p;
    i = j + 1;
  }
  return out;
}

const FATORES = [
  ['dy', 'dyScore', true],
  ['pvp', 'pvp', false],
  ['consistencia', 'consistencia', true],
  ['liquidez', 'liquidez', true],
];

/** Menor entre DY 12m e DY mediano, ignorando ausentes — como o `min` do pandas. */
function dyScore(f, usarMediano) {
  const a = f.dy12m, b = f.dyMediano;
  if (!usarMediano) return a ?? null;
  const vs = [a, b].filter(v => v != null && isFinite(v));
  return vs.length ? Math.min(...vs) : null;
}

/** Devolve uma cópia dos fundos com score, percentis e posição. */
function calcularScore(fundos, pesos, { usarMediano = true, porFamilia = false } = {}) {
  const lista = fundos.map(f => ({ ...f, dyScore: dyScore(f, usarMediano) }));
  const soma = Object.values(pesos).reduce((a, b) => a + b, 0) || 1;
  const w = Object.fromEntries(Object.entries(pesos).map(([k, v]) => [k, v / soma]));

  const grupos = porFamilia
    ? [...new Set(lista.map(f => f.familia || '—'))].map(
        g => lista.map((f, i) => i).filter(i => (lista[i].familia || '—') === g))
    : [lista.map((f, i) => i)];

  for (const g of grupos) {
    const acumulado = new Array(g.length).fill(0);
    for (const [nome, campo, maior] of FATORES) {
      const pc = percentil(g.map(i => lista[i][campo]), maior);
      pc.forEach((v, k) => {
        lista[g[k]]['pc' + nome] = v;
        acumulado[k] += w[nome] * v;
      });
    }
    // O score arredondado é o que vai para a tela E o que ordena o ranking.
    // Ordenar pelo valor cheio e mostrar o arredondado produziria a tela em que
    // dois fundos aparecem com "72,4" e um está acima do outro sem explicação.
    const notas = g.map((_, k) => Math.round(acumulado[k] * 1000) / 10);
    g.forEach((_, k) => { lista[g[k]].score = notas[k]; });

    // Posição dentro do grupo. Empates recebem a MENOR posição do bloco — é o
    // `rank(method='min')` do pandas, e é o que faz dois fundos empatados serem
    // ambos "3º" em vez de um deles virar 4º por causa da ordem do arquivo.
    const ordenado = g.map((_, k) => k).sort((a, b) => notas[b] - notas[a]);
    let anterior = null, posAnterior = 0;
    ordenado.forEach((k, i) => {
      if (anterior === null || notas[k] !== anterior) {
        posAnterior = i + 1; anterior = notas[k];
      }
      lista[g[k]].posicao = posAnterior;
    });
  }
  return lista;
}

// ===========================================================================
// Gráficos (SVG puro, sem biblioteca)
// ===========================================================================
const NS = 'http://www.w3.org/2000/svg';
const mk = (t, a = {}) => {
  const e = document.createElementNS(NS, t);
  for (const k in a) e.setAttribute(k, a[k]);
  return e;
};
const tip = el('tip');
function mostrarTip(ev, html) {
  tip.innerHTML = html;
  tip.style.opacity = '1';
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - r.height - 12;
  if (x + r.width > innerWidth - 10) x = ev.clientX - r.width - 14;
  if (y < 8) y = ev.clientY + 18;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const esconderTip = () => { tip.style.opacity = '0'; };
function ligarTip(node, html) {
  node.addEventListener('mousemove', (e) => mostrarTip(e, html));
  node.addEventListener('mouseleave', esconderTip);
}

const CORES = { 'Papel': '--s1', 'Tijolo': '--s3', 'Híbrido': '--s2' };
const corFamilia = (f) => css(CORES[f] || '--ink-3');

function moldura(svg, altura) {
  svg.textContent = '';
  const w = svg.clientWidth || svg.parentNode.clientWidth || 640;
  svg.setAttribute('viewBox', `0 0 ${w} ${altura}`);
  svg.setAttribute('height', altura);
  return w;
}

/** Dispersão DY x P/VP. Clicar num ponto inclui ou tira o fundo da carteira. */
function dispersao(svg, dados, aoClicar) {
  const h = 420, w = moldura(svg, h);
  const m = { t: 14, r: 18, b: 46, l: 62 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const pts = dados.filter(d => isFinite(d.dy12m) && isFinite(d.pvp));
  if (!pts.length) return;

  const xs = pts.map(d => d.dy12m), ys = pts.map(d => d.pvp);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const px = (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * iw;
  const py = (v) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;

  for (let k = 0; k <= 4; k++) {
    const gy = m.t + (ih * k) / 4, gx = m.l + (iw * k) / 4;
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: gy, y2: gy, class: 'gridline', 'stroke-width': 1 }));
    svg.appendChild(mk('line', { x1: gx, x2: gx, y1: m.t, y2: m.t + ih, class: 'gridline', 'stroke-width': 1 }));
    const ty = mk('text', { x: m.l - 9, y: gy + 4, 'text-anchor': 'end', 'font-size': 11 });
    ty.textContent = num(y1 - (y1 - y0) * k / 4, 2); svg.appendChild(ty);
    const tx = mk('text', { x: gx, y: m.t + ih + 18, 'text-anchor': 'middle', 'font-size': 11 });
    tx.textContent = pct(x0 + (x1 - x0) * k / 4, 1); svg.appendChild(tx);
  }
  // linha do P/VP = 1: acima dela o mercado paga ágio sobre o laudo
  if (y0 < 1 && y1 > 1) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(1), y2: py(1),
      stroke: css('--line-strong'), 'stroke-width': 1, 'stroke-dasharray': '4 4' }));
    const t = mk('text', { x: m.l + iw - 4, y: py(1) - 5, 'text-anchor': 'end', 'font-size': 10.5 });
    t.textContent = 'P/VP = 1'; svg.appendChild(t);
  }

  const rot = mk('text', { x: m.l + iw / 2, y: h - 8, 'text-anchor': 'middle', 'font-size': 11.5 });
  rot.textContent = 'Dividend yield dos últimos 12 meses'; svg.appendChild(rot);
  const roty = mk('text', { x: 14, y: m.t + ih / 2, 'font-size': 11.5, 'text-anchor': 'middle',
    transform: `rotate(-90 14 ${m.t + ih / 2})` });
  roty.textContent = 'P/VP'; svg.appendChild(roty);

  pts.forEach(d => {
    const escolhido = estado.sel.has(d.ticker);
    const c = mk('circle', {
      cx: px(d.dy12m), cy: py(d.pvp), r: escolhido ? 6.5 : 4.5,
      fill: escolhido ? corFamilia(d.familia) : 'none',
      stroke: corFamilia(d.familia), 'stroke-width': escolhido ? 2 : 1.4,
      'fill-opacity': .85, cursor: 'pointer',
    });
    ligarTip(c, `<b>${esc(d.ticker)} — ${esc(d.nome || '')}</b>
      <div class="r"><span>DY 12m</span><span>${pct(d.dy12m, 2)}</span></div>
      <div class="r"><span>P/VP</span><span>${num(d.pvp, 2)}</span></div>
      <div class="r"><span>Score</span><span>${num(d.score, 1)}</span></div>
      <div class="r"><span>${escolhido ? 'na carteira' : 'clique para incluir'}</span><span></span></div>`);
    c.addEventListener('click', () => aoClicar(d.ticker));
    svg.appendChild(c);
  });
}

/** Barras horizontais rotuladas. */
function barras(svg, dados) {
  const n = dados.length;
  if (!n) { moldura(svg, 10); return; }
  const alt = 22, gap = 6, m = { t: 8, r: 76, b: 10, l: 132 };
  const h = m.t + n * (alt + gap) + m.b;
  const w = moldura(svg, h);
  const iw = Math.max(w - m.l - m.r, 80);
  const max = Math.max(...dados.map(d => d.v)) * 1.02 || 1;

  dados.forEach((d, i) => {
    const y = m.t + i * (alt + gap);
    const lw = Math.max((d.v / max) * iw, 2);
    const b = mk('rect', { x: m.l, y, width: lw, height: alt, rx: 4, fill: d.cor || css('--s1') });
    if (d.tip) ligarTip(b, d.tip);
    svg.appendChild(b);
    const rotulo = mk('text', { x: m.l - 9, y: y + alt / 2 + 4, 'text-anchor': 'end', 'font-size': 12 });
    rotulo.textContent = d.k; svg.appendChild(rotulo);
    const val = mk('text', { x: m.l + lw + 7, y: y + alt / 2 + 4, 'font-size': 11.5 });
    val.textContent = d.rotulo || pct(d.v, 1); svg.appendChild(val);
  });
}

/** Colunas no tempo — usada para a renda mensal da carteira. */
function colunas(svg, rotulos, valores) {
  const h = 300, w = moldura(svg, h);
  const m = { t: 14, r: 16, b: 40, l: 68 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const validos = valores.filter(v => isFinite(v));
  if (!validos.length) return;
  const max = Math.max(...validos) * 1.1 || 1;
  const larg = Math.max(iw / valores.length - 3, 2);

  for (let k = 0; k <= 4; k++) {
    const gy = m.t + (ih * k) / 4;
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: gy, y2: gy, class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: m.l - 9, y: gy + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = compacto(max * (1 - k / 4)); svg.appendChild(t);
  }

  // A média é desenhada DEPOIS das colunas, senão elas passam por cima da
  // linha e do rótulo — que foi exatamente o que aconteceu na primeira versão.
  valores.forEach((v, i) => {
    if (!isFinite(v)) return;
    const alt = Math.max((v / max) * ih, 1);
    const x = m.l + (iw * i) / valores.length;
    const r = mk('rect', { x, y: m.t + ih - alt, width: larg, height: alt, rx: 2, fill: css('--s1') });
    ligarTip(r, `<b>${esc(rotulos[i] || '')}</b>
      <div class="r"><span>Renda</span><span>${brl(v, 2)}</span></div>`);
    svg.appendChild(r);
    if (i % Math.ceil(valores.length / 8) === 0) {
      const t = mk('text', { x: x + larg / 2, y: h - 14, 'text-anchor': 'middle', 'font-size': 10.5 });
      t.textContent = (rotulos[i] || '').slice(2); svg.appendChild(t);
    }
  });

  const media = validos.reduce((a, b) => a + b, 0) / validos.length;
  const ym = m.t + ih - (media / max) * ih;
  svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: ym, y2: ym,
    stroke: css('--s2'), 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
  // A linha da média cruza as colunas, então o rótulo precisa de um fundo opaco
  // atrás. A largura vem do `getBBox` depois de inserido: estimar por número de
  // caracteres erra a conta e o texto volta a ficar por cima das barras.
  const tm = mk('text', { x: m.l + iw - 5, y: ym - 7, 'text-anchor': 'end',
    'font-size': 11, fill: css('--s2') });
  tm.textContent = 'média ' + brl(media, 0);
  svg.appendChild(tm);
  try {
    const cx = tm.getBBox();
    const fundo = mk('rect', { x: cx.x - 5, y: cx.y - 2, rx: 4,
      width: cx.width + 10, height: cx.height + 4,
      fill: css('--surface-1'), 'fill-opacity': .93 });
    svg.insertBefore(fundo, tm);
  } catch (e) { /* getBBox falha com o svg ainda fora da tela; segue sem fundo */ }

}

// ===========================================================================
// Estado
// ===========================================================================
let D = null;
let comScore = [];
const estado = {
  pesos: { dy: 35, pvp: 30, consistencia: 20, liquidez: 15 },
  liqMin: 500000, capital: 100000, wmax: 0.20,
  usarMediano: true, porFamilia: true,
  // A ordenação padrão é pelo score, não pela posição: com o ranking separado
  // por família, ordenar por posição intercala o nº 1 de papel, o nº 1 de
  // tijolo e o nº 1 de híbrido, e a coluna de score aparece fora de ordem sem
  // que nada na tela explique por quê.
  familia: 'todas', busca: '', ordem: 'score', dir: 'desc',
  metodo: 'igual',
  sel: new Set(),
};

const CHAVE_SALVA = 'fiis.carteira.v1';
function salvar() {
  try { localStorage.setItem(CHAVE_SALVA, JSON.stringify([...estado.sel])); }
  catch (e) { /* navegador sem armazenamento: a escolha só vale nesta visita */ }
}
function carregarSalvo() {
  try {
    const bruto = localStorage.getItem(CHAVE_SALVA);
    if (bruto) JSON.parse(bruto).forEach(t => estado.sel.add(t));
  } catch (e) { /* idem */ }
}

// escala do controle de liquidez: 0, 100 mil, 200 mil, ... 3 milhões
const liqDoPasso = (p) => p * 100000;

// ===========================================================================
// Universo, ranking e tabela
// ===========================================================================
function universo() {
  return (D.fundos || []).filter(f => (f.liquidez ?? 0) >= estado.liqMin);
}

function ranquear() {
  comScore = calcularScore(universo(), estado.pesos, {
    usarMediano: estado.usarMediano, porFamilia: estado.porFamilia,
  });
  return comScore;
}

function visiveis() {
  const q = estado.busca.trim().toLowerCase();
  let lista = comScore;
  if (estado.familia !== 'todas') lista = lista.filter(f => f.familia === estado.familia);
  if (q) {
    lista = lista.filter(f => [f.ticker, f.nome, f.segmento, f.admin, f.mandato]
      .some(v => String(v ?? '').toLowerCase().includes(q)));
  }
  const c = estado.ordem, sinal = estado.dir === 'asc' ? 1 : -1;
  const cmp = (va, vb) => {
    if (va == null && vb == null) return 0;
    if (va == null) return 1;          // ausente vai para o fim nos dois sentidos
    if (vb == null) return -1;
    return typeof va === 'string' ? va.localeCompare(vb, 'pt-BR') : va - vb;
  };
  return [...lista].sort((a, b) =>
    sinal * cmp(a[c], b[c])
    // desempate estável pelo score: sem isto, ordenar por uma coluna com muitos
    // empates (posição, consistência) devolve a ordem do arquivo, que muda a
    // cada coleta e faz a tabela "pular" sem motivo entre dois dias.
    || cmp(b.score, a.score)
    || cmp(a.ticker, b.ticker));
}

function renderTiles() {
  const u = comScore;
  const med = (campo) => {
    const v = u.map(f => f[campo]).filter(x => x != null && isFinite(x)).sort((a, b) => a - b);
    return v.length ? v[Math.floor(v.length / 2)] : null;
  };
  const dados = [
    ['Fundos na lista', String(u.length), `${D.meta.excluidos || 0} fora dos filtros`],
    ['DY mediano', pct(med('dy12m'), 1), 'últimos 12 meses'],
    ['P/VP mediano', num(med('pvp'), 2), 'sobre o informe da CVM'],
    ['Patrimônio somado', compacto(u.reduce((s, f) => s + (f.pl || 0), 0)), 'dos fundos listados'],
    ['Competência', D.meta.competencia_informe || '—', 'informe mensal usado'],
  ];
  el('tiles').innerHTML = dados.map(([k, v, h]) =>
    `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>
     <div class="h">${esc(h)}</div></div>`).join('');
}

function renderChips() {
  const fams = ['todas', ...new Set(comScore.map(f => f.familia).filter(Boolean))];
  el('chips').innerHTML = fams.map(f =>
    `<button data-f="${esc(f)}" aria-pressed="${f === estado.familia}">${
      f === 'todas' ? 'Todos' : esc(f)}</button>`).join('');
  el('chips').querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => { estado.familia = b.dataset.f; render(); }));
}

function linhaRank(f) {
  const marcado = estado.sel.has(f.ticker);
  const fam = (f.familia || '').toLowerCase().replace('í', 'i');
  return `<tr class="${marcado ? 'escolhido' : ''}" data-t="${esc(f.ticker)}">
    <td class="sel"><input type="checkbox" ${marcado ? 'checked' : ''}
        aria-label="incluir ${esc(f.ticker)} na carteira"></td>
    <td class="l num">${f.posicao ?? '—'}</td>
    <td class="l"><span class="tk">${esc(f.ticker)}</span>
        <div class="muted cap" title="${esc(f.nome || '')}">${esc(f.nome || '')}</div></td>
    <td class="l"><span class="pill ${fam}">${esc(f.familia || '—')}</span>
        <div class="muted cap">${esc(f.segmento || '')}</div></td>
    <td class="num"><div style="display:flex;align-items:center;gap:7px;justify-content:flex-end">
        <span>${num(f.score, 1)}</span>
        <span class="barra" style="width:46px"><i style="width:${Math.max(0, Math.min(100, f.score || 0))}%"></i></span>
      </div></td>
    <td class="num">${pct(f.dy12m, 2)}</td>
    <td class="num">${num(f.pvp, 2)}</td>
    <td class="num">${pct(f.consistencia, 0)}</td>
    <td class="num">${brl(f.rendMensal, 2)}</td>
    <td class="num">${brl(f.preco, 2)}</td>
    <td class="num">${compacto(f.liquidez)}</td>
    <td class="num">${compacto(f.pl)}</td>
    <td class="l alerta">${esc(f.alerta || '')}</td>
  </tr>`;
}

function renderRanking() {
  const lista = visiveis();
  const corpo = el('tbRank').querySelector('tbody');
  corpo.innerHTML = lista.length ? lista.map(linhaRank).join('')
    : '<tr><td colspan="13" class="vazio">Nenhum fundo passa nos filtros atuais.</td></tr>';
  corpo.querySelectorAll('tr[data-t]').forEach(tr => {
    tr.querySelector('input').addEventListener('change', () => alternar(tr.dataset.t));
  });
  document.querySelectorAll('#tbRank th.ord').forEach(th => {
    th.removeAttribute('data-dir');
    if (th.dataset.c === estado.ordem) th.setAttribute('data-dir', estado.dir);
  });
  el('rodapeRank').textContent =
    `${lista.length} de ${comScore.length} fundos. ` +
    (estado.porFamilia
      ? 'A numeração é dentro de cada família — o nº 1 de papel e o nº 1 de tijolo são dois fundos diferentes.'
      : 'Numeração única para papel, tijolo e híbrido; compare P/VP entre famílias com cuidado.');
  dispersao(el('chDisp'), lista, alternar);
}

function alternar(ticker) {
  if (estado.sel.has(ticker)) estado.sel.delete(ticker); else estado.sel.add(ticker);
  salvar();
  render();
}

// ===========================================================================
// Carteira
// ===========================================================================
/** Pesos brutos conforme o método, já normalizados e com teto aplicado. */
function pesosCarteira(escolhidos) {
  let bruto;
  if (estado.metodo === 'score') {
    bruto = escolhidos.map(f => Math.max(f.score || 0, 1));
  } else if (estado.metodo === 'renda') {
    // renda igual por fundo: peso inversamente proporcional ao yield
    bruto = escolhidos.map(f => (f.dy12m && f.dy12m > 0) ? 1 / f.dy12m : 0);
    if (!bruto.some(v => v > 0)) bruto = escolhidos.map(() => 1);
  } else {
    bruto = escolhidos.map(() => 1);
  }
  let total = bruto.reduce((a, b) => a + b, 0) || 1;
  let w = bruto.map(v => v / total);

  // teto por fundo: corta quem passou e redistribui entre os demais.
  const teto = Math.max(estado.wmax, 1 / escolhidos.length);
  for (let passo = 0; passo < 60; passo++) {
    const excede = w.map(v => v > teto + 1e-12);
    if (!excede.some(Boolean)) break;
    const sobra = w.reduce((s, v, i) => s + (excede[i] ? v - teto : 0), 0);
    const base = w.reduce((s, v, i) => s + (excede[i] ? 0 : v), 0) || 1;
    w = w.map((v, i) => excede[i] ? teto : v + sobra * (v / base));
  }
  return w;
}

function renderCarteira() {
  const escolhidos = comScore.filter(f => estado.sel.has(f.ticker));
  el('nSel').textContent = estado.sel.size ? `(${estado.sel.size})` : '';
  el('carteiraVazia').classList.toggle('hidden', escolhidos.length > 0);
  el('carteiraCheia').classList.toggle('hidden', escolhidos.length === 0);
  if (!escolhidos.length) return;

  const w = pesosCarteira(escolhidos);
  const linhas = escolhidos.map((f, i) => {
    const alvo = estado.capital * w[i];
    const cotas = f.preco > 0 ? Math.floor(alvo / f.preco) : 0;
    const valor = cotas * (f.preco || 0);
    return { f, peso: w[i], cotas, valor, renda: cotas * (f.rendMensal || 0) };
  });

  const investido = linhas.reduce((s, l) => s + l.valor, 0);
  const renda = linhas.reduce((s, l) => s + l.renda, 0);
  const pesoReal = (l) => investido > 0 ? l.valor / investido : 0;
  const dyCart = investido > 0 ? (renda * 12) / investido : null;
  const pvpCart = investido > 0
    ? linhas.reduce((s, l) => s + pesoReal(l) * (l.f.pvp || 0), 0) : null;
  const consCart = investido > 0
    ? linhas.reduce((s, l) => s + pesoReal(l) * (l.f.consistencia || 0), 0) : null;

  el('tilesCart').innerHTML = [
    ['Renda mensal estimada', brl(renda, 2), 'pelos rendimentos dos últimos 12 meses'],
    ['DY da carteira', pct(dyCart, 2), 'sobre o valor investido'],
    ['P/VP médio', num(pvpCart, 2), 'ponderado pelo valor'],
    ['Consistência média', pct(consCart, 0), 'ponderada pelo valor'],
    ['Investido', brl(investido, 0), `${linhas.length} fundos`],
  ].map(([k, v, h]) =>
    `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>
     <div class="h">${esc(h)}</div></div>`).join('');

  const corpo = el('tbCart').querySelector('tbody');
  corpo.innerHTML = [...linhas].sort((a, b) => b.valor - a.valor).map(l => `
    <tr data-t="${esc(l.f.ticker)}">
      <td class="l"><span class="tk">${esc(l.f.ticker)}</span>
          <div class="muted cap">${esc(l.f.segmento || '')}</div></td>
      <td class="num">${pct(pesoReal(l), 1)}</td>
      <td class="num">${brl(l.f.preco, 2)}</td>
      <td class="num">${num(l.cotas, 0)}</td>
      <td class="num">${brl(l.valor, 0)}</td>
      <td class="num">${brl(l.renda, 2)}</td>
      <td class="sel"><button class="btn sec" style="padding:2px 8px" title="tirar da carteira">×</button></td>
    </tr>`).join('');
  corpo.querySelectorAll('tr[data-t]').forEach(tr =>
    tr.querySelector('button').addEventListener('click', () => alternar(tr.dataset.t)));

  const sobra = estado.capital - investido;
  el('sobra').textContent = sobra > 0.005
    ? `Sobram ${brl(sobra, 2)} — o resto de dividir o capital por cotas inteiras.`
    : 'O capital coube inteiro em cotas.';

  // ---- concentração por segmento --------------------------------------
  const porSeg = new Map();
  linhas.forEach(l => {
    const k = l.f.segmento || l.f.familia || 'Sem classificação';
    porSeg.set(k, (porSeg.get(k) || 0) + pesoReal(l));
  });
  const segs = [...porSeg.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => ({
    k: k.length > 22 ? k.slice(0, 21) + '…' : k, v,
    tip: `<b>${esc(k)}</b><div class="r"><span>Peso</span><span>${pct(v, 1)}</span></div>`,
  }));
  barras(el('chSeg'), segs);

  const maior = segs[0];
  const conc = maior && maior.v > 0.40;
  el('avisoConc').classList.toggle('hidden', !conc);
  if (conc) {
    el('avisoConc').innerHTML =
      `<b>${pct(maior.v, 0)} da carteira em ${esc(maior.k)}.</b> Fundos do mesmo
       segmento respondem juntos ao mesmo choque — vacância de escritório,
       queda de venda no varejo, alta de juros para os de papel. Diversificar
       entre códigos sem diversificar entre segmentos não reduz esse risco.`;
  }

  // ---- renda mensal histórica -----------------------------------------
  const meses = D.meses || [];
  if (meses.length) {
    const soma = meses.map((_, i) => linhas.reduce((s, l) => {
      const serie = l.f.serie || [];
      const desloc = serie.length - meses.length;
      const v = serie[i + desloc];
      return s + (isFinite(v) ? v * l.cotas : 0);
    }, 0));
    colunas(el('chRenda'), meses, soma);
  }
}

// ===========================================================================
// Render e controles
// ===========================================================================
function render() {
  ranquear();
  renderTiles();
  renderChips();
  renderRanking();
  renderCarteira();
}

function trocarAba(nome) {
  document.querySelectorAll('.tabs button').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.p === nome)));
  ['ranking', 'carteira', 'excluidos', 'metodo'].forEach(p =>
    el('p-' + p).classList.toggle('hidden', p !== nome));
  render();
}

function ligarControles() {
  const peso = (id, chave, rot) => el(id).addEventListener('input', () => {
    estado.pesos[chave] = +el(id).value;
    el(rot).textContent = el(id).value;
    render();
  });
  peso('ctlDy', 'dy', 'lblDy');
  peso('ctlPvp', 'pvp', 'lblPvp');
  peso('ctlCons', 'consistencia', 'lblCons');
  peso('ctlLiq', 'liquidez', 'lblLiq');

  el('ctlLiqMin').addEventListener('input', () => {
    estado.liqMin = liqDoPasso(+el('ctlLiqMin').value);
    el('lblLiqMin').textContent = estado.liqMin ? compacto(estado.liqMin) : 'sem mínimo';
    render();
  });
  el('ctlCap').addEventListener('input', () => {
    estado.capital = Math.max(+el('ctlCap').value || 0, 0);
    renderCarteira();
  });
  el('ctlWmax').addEventListener('input', () => {
    estado.wmax = +el('ctlWmax').value / 100;
    el('lblWmax').textContent = el('ctlWmax').value + '%';
    renderCarteira();
  });
  el('ctlMetodo').addEventListener('change', () => {
    estado.metodo = el('ctlMetodo').value;
    renderCarteira();
  });
  el('ctlFamilia').addEventListener('change', () => {
    estado.porFamilia = el('ctlFamilia').checked; render();
  });
  el('ctlMediano').addEventListener('change', () => {
    estado.usarMediano = el('ctlMediano').checked; render();
  });
  let t;
  el('ctlBusca').addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(() => { estado.busca = el('ctlBusca').value; renderRanking(); }, 140);
  });
  document.querySelectorAll('#tbRank th.ord').forEach(th =>
    th.addEventListener('click', () => {
      const c = th.dataset.c;
      if (estado.ordem === c) estado.dir = estado.dir === 'asc' ? 'desc' : 'asc';
      else { estado.ordem = c; estado.dir = (c === 'posicao' || c === 'pvp' || c === 'ticker') ? 'asc' : 'desc'; }
      renderRanking();
    }));
  el('btnTop10').addEventListener('click', () => {
    visiveis().slice(0, 10).forEach(f => estado.sel.add(f.ticker));
    salvar(); trocarAba('carteira');
  });
  document.querySelectorAll('.tabs button').forEach(b =>
    b.addEventListener('click', () => trocarAba(b.dataset.p)));
  let r;
  addEventListener('resize', () => { clearTimeout(r); r = setTimeout(render, 160); });
}

// ===========================================================================
async function iniciar() {
  try {
    const resp = await fetch('fiis.json?v=' + Date.now());
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    D = await resp.json();
  } catch (e) {
    el('loading').classList.add('hidden');
    const box = el('erro');
    box.classList.remove('hidden');
    box.innerHTML = `<p><b>Não foi possível carregar os dados dos fundos.</b></p>
      <p>O arquivo <code>fiis.json</code> não foi encontrado. Rode a ação
      <b>Atualizar FIIs</b> no GitHub para gerá-lo.</p>
      <p class="muted">${esc(e.message)}</p>`;
    return;
  }

  el('stamp').textContent = D.meta.gerado_em || '—';
  const demo = !!D.meta.demo;
  el('stampFonte').textContent = demo
    ? '⚠ dados sintéticos de demonstração'
    : `${(D.fundos || []).length} fundos no universo · informe de ${D.meta.competencia_informe || '—'}`;
  el('dadosDemo').classList.toggle('hidden', !demo);

  el('tbExc').querySelector('tbody').innerHTML = (D.excluidos || []).map(e =>
    `<tr><td class="l tk">${esc(e.ticker || '—')}</td>
      <td class="l cap" title="${esc(e.nome || '')}">${esc(e.nome || '—')}</td>
      <td class="l cap muted">${esc(e.segmento || '—')}</td>
      <td class="l muted">${esc(e.motivo || '—')}</td></tr>`).join('')
    || '<tr><td colspan="4" class="l muted">Nenhum fundo excluído.</td></tr>';

  const p = D.meta.pesosPadrao;
  if (p) {
    estado.pesos = { dy: Math.round(p.dy * 100), pvp: Math.round(p.pvp * 100),
      consistencia: Math.round(p.consistencia * 100), liquidez: Math.round(p.liquidez * 100) };
    [['ctlDy', 'lblDy', 'dy'], ['ctlPvp', 'lblPvp', 'pvp'],
     ['ctlCons', 'lblCons', 'consistencia'], ['ctlLiq', 'lblLiq', 'liquidez']]
      .forEach(([c, l, k]) => { el(c).value = estado.pesos[k]; el(l).textContent = estado.pesos[k]; });
  }
  const liqPadrao = D.meta.filtros?.liquidez;
  if (liqPadrao != null) {
    estado.liqMin = liqPadrao;
    el('ctlLiqMin').value = String(Math.round(liqPadrao / 100000));
    el('lblLiqMin').textContent = liqPadrao ? compacto(liqPadrao) : 'sem mínimo';
  }

  carregarSalvo();
  // um fundo salvo que saiu do universo não pode ficar assombrando a carteira
  const existentes = new Set((D.fundos || []).map(f => f.ticker));
  [...estado.sel].forEach(t => { if (!existentes.has(t)) estado.sel.delete(t); });

  ligarControles();
  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  render();
}

iniciar();
