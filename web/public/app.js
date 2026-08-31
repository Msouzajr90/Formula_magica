/* Fórmula Mágica B3 — front-end estático.
   Lê dados.json (gerado pelo Python) e refaz ranking e otimização no navegador.
   Sem dependências externas. */
'use strict';

// ===========================================================================
// Otimizador de Markowitz
// ===========================================================================

/** Projeta v no conjunto {w : soma(w)=1, 0 <= w_i <= cap}.
 *  Busca binária no deslocamento tau tal que soma(clip(v-tau,0,cap)) = 1.
 *  A soma é monótona decrescente em tau, então a bissecção sempre converge. */
function projetar(v, cap) {
  const n = v.length;
  if (cap * n < 1) cap = 1 / n;               // sem isso o conjunto seria vazio
  const soma = (tau) => {
    let s = 0;
    for (let i = 0; i < n; i++) s += Math.min(Math.max(v[i] - tau, 0), cap);
    return s;
  };
  let lo = Math.min(...v) - 1, hi = Math.max(...v);
  for (let k = 0; k < 80; k++) {
    const mid = (lo + hi) / 2;
    if (soma(mid) > 1) lo = mid; else hi = mid;
  }
  const tau = (lo + hi) / 2, w = new Float64Array(n);
  for (let i = 0; i < n; i++) w[i] = Math.min(Math.max(v[i] - tau, 0), cap);
  let s = 0; for (let i = 0; i < n; i++) s += w[i];
  if (s > 0) for (let i = 0; i < n; i++) w[i] /= s;
  return w;
}

function mulMatVec(S, w) {
  const n = w.length, out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let acc = 0, linha = S[i];
    for (let j = 0; j < n; j++) acc += linha[j] * w[j];
    out[i] = acc;
  }
  return out;
}

const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };

/** Minimiza  w'Σw − lambda·w'μ  sujeito a soma=1 e 0<=w<=cap.
 *  Gradiente projetado com passo fixo 1/L, L estimado por Gershgorin. */
function otimizar(S, mu, cap, lambda, iteracoes = 900) {
  const n = mu.length;
  if (n === 0) return new Float64Array(0);
  if (n === 1) return Float64Array.from([1]);

  let L = 0;
  for (let i = 0; i < n; i++) {
    let soma = 0;
    for (let j = 0; j < n; j++) soma += Math.abs(S[i][j]);
    if (soma > L) L = soma;
  }
  const passo = 1 / (2 * L + 1e-12);

  let w = new Float64Array(n).fill(1 / n);
  for (let k = 0; k < iteracoes; k++) {
    const Sw = mulMatVec(S, w), y = new Float64Array(n);
    for (let i = 0; i < n; i++) y[i] = w[i] - passo * (2 * Sw[i] - lambda * mu[i]);
    const novo = projetar(y, cap);
    let dif = 0;
    for (let i = 0; i < n; i++) dif += Math.abs(novo[i] - w[i]);
    w = novo;
    if (dif < 1e-10) break;
  }
  return w;
}

const risco = (S, w) => Math.sqrt(Math.max(dot(w, mulMatVec(S, w)), 0));

/** Traça a fronteira variando lambda; devolve pontos únicos ordenados por risco. */
function fronteira(S, mu, cap, pontos = 20) {
  const escala = Math.max(...mu.map(Math.abs)) || 1;
  const lambdas = [0];
  for (let k = 0; k < 60; k++) lambdas.push(Math.pow(1.28, k) * 1e-3 / escala);

  const bruto = [];
  for (const lam of lambdas) {
    const w = otimizar(S, mu, cap, lam);
    bruto.push({ w, ret: dot(w, mu), vol: risco(S, w) });
  }
  bruto.sort((a, b) => a.vol - b.vol);

  // remove duplicatas e pontos dominados (mesmo risco, retorno menor)
  const limpo = [];
  for (const p of bruto) {
    const ult = limpo[limpo.length - 1];
    if (ult && p.vol - ult.vol < 1e-5) { if (p.ret > ult.ret) limpo[limpo.length - 1] = p; continue; }
    if (ult && p.ret <= ult.ret + 1e-9) continue;
    limpo.push(p);
  }
  if (limpo.length <= pontos) return limpo;
  const passo = (limpo.length - 1) / (pontos - 1);
  return Array.from({ length: pontos }, (_, i) => limpo[Math.round(i * passo)]);
}

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
  if (a >= 1e6) return 'R$ ' + nf(1).format(v / 1e6) + ' mi';
  if (a >= 1e3) return 'R$ ' + nf(0).format(v / 1e3) + ' mil';
  return brl(v, 0);
}
const el = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();

// ===========================================================================
// Gráficos (SVG puro)
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

/** Barras horizontais — uma série, rótulos diretos, sem legenda. */
function barras(svg, dados) {
  svg.textContent = '';
  const n = dados.length;
  if (!n) return;
  const alturaBarra = 21, gap = 5, m = { t: 8, r: 66, b: 26, l: 62 };
  const h = m.t + n * (alturaBarra + gap) + m.b;
  const w = svg.clientWidth || svg.parentNode.clientWidth || 620;
  const iw = Math.max(w - m.l - m.r, 80);
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('height', h);

  const max = Math.max(...dados.map(d => d.v)) * 1.02;
  const x = (v) => (v / max) * iw;

  for (let k = 0; k <= 4; k++) {
    const gx = m.l + (iw * k) / 4;
    svg.appendChild(mk('line', { x1: gx, x2: gx, y1: m.t, y2: h - m.b, class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: gx, y: h - m.b + 15, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = nf(0).format((max * k / 4) * 100) + '%';
    svg.appendChild(t);
  }

  dados.forEach((d, i) => {
    const y = m.t + i * (alturaBarra + gap);
    const lw = Math.max(x(d.v), 2);
    const b = mk('rect', { x: m.l, y, width: lw, height: alturaBarra, rx: 4, fill: css('--s1') });
    ligarTip(b, `<b>${d.k}</b><div class="r"><span>Peso</span><span>${pct(d.v, 2)}</span></div>
                 <div class="r"><span>Valor</span><span>${compacto(d.valor)}</span></div>`);
    svg.appendChild(b);

    const rot = mk('text', { x: m.l - 9, y: y + alturaBarra / 2 + 4, 'text-anchor': 'end', 'font-size': 12 });
    rot.textContent = d.k; svg.appendChild(rot);

    const val = mk('text', { x: m.l + lw + 7, y: y + alturaBarra / 2 + 4, 'font-size': 11.5 });
    val.textContent = pct(d.v, 1); svg.appendChild(val);
  });
}

/** Dispersão genérica com dois grupos de cor (identidade, não posto). */
function dispersao(svg, pontos, opts) {
  svg.textContent = '';
  const m = { t: 14, r: 18, b: 46, l: 62 };
  const w = svg.clientWidth || svg.parentNode.clientWidth || 620;
  const h = opts.altura || 380;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('height', h);
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  if (!pontos.length) return;

  const xs = pontos.map(p => p.x), ys = pontos.map(p => p.y);
  const pad = (a) => { const lo = Math.min(...a), hi = Math.max(...a); const d = (hi - lo) || Math.abs(hi) || 1; return [lo - d * .08, hi + d * .08]; };
  const [x0, x1] = pad(xs), [y0, y1] = pad(ys);
  const X = (v) => m.l + ((v - x0) / (x1 - x0)) * iw;
  const Y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

  for (let k = 0; k <= 4; k++) {
    const gy = m.t + (ih * k) / 4, val = y1 - ((y1 - y0) * k) / 4;
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: gy, y2: gy, class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: m.l - 9, y: gy + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = opts.fy(val); svg.appendChild(t);
  }
  for (let k = 0; k <= 4; k++) {
    const gx = m.l + (iw * k) / 4, val = x0 + ((x1 - x0) * k) / 4;
    const t = mk('text', { x: gx, y: h - m.b + 18, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = opts.fx(val); svg.appendChild(t);
  }
  const tx = mk('text', { x: m.l + iw / 2, y: h - 8, 'text-anchor': 'middle', 'font-size': 11.5 });
  tx.textContent = opts.rotuloX; svg.appendChild(tx);
  const ty = mk('text', { x: 14, y: m.t + ih / 2, 'text-anchor': 'middle', 'font-size': 11.5,
                          transform: `rotate(-90 14 ${m.t + ih / 2})` });
  ty.textContent = opts.rotuloY; svg.appendChild(ty);

  if (opts.linha) {
    const ord = [...pontos].sort((a, b) => a.x - b.x);
    svg.appendChild(mk('path', {
      d: 'M' + ord.map(p => `${X(p.x)},${Y(p.y)}`).join('L'),
      fill: 'none', stroke: css('--s1'), 'stroke-width': 2, 'stroke-linejoin': 'round'
    }));
  }

  pontos.forEach(p => {
    const c = mk('circle', {
      cx: X(p.x), cy: Y(p.y), r: p.destaque ? 8 : 5,
      fill: p.destaque ? css('--s2') : (p.forte ? css('--s1') : css('--ink-3')),
      stroke: css('--surface-1'), 'stroke-width': 2,
      opacity: p.forte || p.destaque ? 1 : .55
    });
    ligarTip(c, p.tip);
    svg.appendChild(c);
  });
}

// ===========================================================================
// Estado e renderização
// ===========================================================================
let D = null;                      // dados.json
let idx = new Map();               // ticker -> empresa
let estado = { n: 30, cap: 0.15, perfil: 0, capital: 100000, unico: true };
let frontAtual = [];

function elegiveis() {
  let lista = D.empresas.filter(e => idx.has(e.ticker));
  if (estado.unico) {
    const vistos = new Set(), fora = [];
    for (const e of lista) {
      const raiz = e.ticker.replace(/\d+$/, '');
      if (vistos.has(raiz)) continue;
      vistos.add(raiz); fora.push(e);
    }
    lista = fora;
  }
  return lista;
}

function calcular() {
  const sel = elegiveis().slice(0, estado.n);
  const pos = new Map(D.estatisticas.tickers.map((t, i) => [t, i]));
  const ids = sel.map(e => pos.get(e.ticker)).filter(i => i !== undefined);

  const mu = ids.map(i => D.estatisticas.mu[i] ?? 0);
  const S = ids.map(i => ids.map(j => D.estatisticas.cov[i][j] ?? 0));
  const nomes = ids.map(i => D.estatisticas.tickers[i]);

  frontAtual = fronteira(S, mu, estado.cap, 20);
  const k = Math.min(estado.perfil, frontAtual.length - 1);
  const p = frontAtual[k] || { w: new Float64Array(nomes.length), ret: 0, vol: 0 };

  const pesos = [];
  nomes.forEach((t, i) => { if (p.w[i] > 0.005) pesos.push({ k: t, v: p.w[i] }); });
  const soma = pesos.reduce((s, d) => s + d.v, 0) || 1;
  pesos.forEach(d => d.v /= soma);
  pesos.sort((a, b) => b.v - a.v);

  return { sel, pesos, ret: p.ret, vol: p.vol, carteira: new Set(pesos.map(d => d.k)) };
}

function render() {
  const r = calcular();
  const rf = D.meta.taxaLivreRisco || 0;
  const sharpe = r.vol > 0 ? (r.ret - rf) / r.vol : NaN;

  // --- tiles ---
  const tiles = [
    ['Ações na carteira', String(r.pesos.length), `de ${estado.n} no ranking`],
    ['Retorno esperado', pct(r.ret), 'ao ano, estimado'],
    ['Volatilidade', pct(r.vol), 'ao ano'],
    ['Índice de Sharpe', num(sharpe), `sobre ${pct(rf, 1)} livre de risco`],
    ['Maior posição', pct(r.pesos[0]?.v || 0), 'concentração máxima'],
  ];
  el('tiles').innerHTML = tiles.map(([k, v, h]) =>
    `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="h">${h}</div></div>`
  ).join('');

  // --- carteira ---
  const cap = estado.capital;
  barras(el('chPesos'), r.pesos.map(d => ({ ...d, valor: d.v * cap })));

  let gasto = 0;
  el('tbOrdem').querySelector('tbody').innerHTML = r.pesos.map(d => {
    const e = idx.get(d.k) || {};
    const preco = e.preco;
    const qtd = preco ? Math.floor((d.v * cap) / preco) : 0;
    const fin = qtd * (preco || 0);
    gasto += fin;
    return `<tr><td class="l tk">${d.k}</td><td class="num">${pct(d.v, 2)}</td>
      <td class="num">${brl(preco)}</td><td class="num">${nf(0).format(qtd)}</td>
      <td class="num">${brl(fin, 0)}</td></tr>`;
  }).join('');
  el('sobra').textContent =
    `Sobra em caixa por arredondamento: ${brl(cap - gasto, 0)} de ${brl(cap, 0)}.`;

  // --- ranking ---
  const lista = elegiveis();
  dispersao(el('chScatter'), lista.slice(0, 60).map(e => ({
    x: e.ey, y: e.roic, forte: r.carteira.has(e.ticker),
    tip: `<b>${e.ticker} — ${e.nome || ''}</b>
      <div class="r"><span>ROIC</span><span>${pct(e.roic)}</span></div>
      <div class="r"><span>Earnings Yield</span><span>${pct(e.ey)}</span></div>
      <div class="r"><span>Soma no ranking</span><span>${e.rank}</span></div>`
  })), { fx: v => pct(v, 0), fy: v => pct(v, 0), rotuloX: 'Earnings Yield (preço)',
         rotuloY: 'ROIC (qualidade)', altura: 400 });

  el('tbRank').querySelector('tbody').innerHTML = lista.slice(0, 120).map((e, i) => {
    const dentro = r.carteira.has(e.ticker);
    return `<tr${dentro ? ' style="background:color-mix(in srgb, var(--s1) 7%, transparent)"' : ''}>
      <td class="l num muted">${i + 1}</td><td class="l tk">${e.ticker}</td>
      <td class="l cap" title="${e.nome || ''}">${e.nome || '—'}</td>
      <td class="l cap muted" title="${e.setor || ''}">${e.setor || '—'}</td>
      <td class="num">${pct(e.roic)}</td><td class="num">${pct(e.ey)}</td>
      <td class="num muted">${e.posRoic}</td><td class="num muted">${e.posEy}</td>
      <td class="num"><b>${e.rank}</b></td>
      <td class="num">${brl(e.preco)}</td><td class="num">${compacto(e.liquidez)}</td></tr>`;
  }).join('');

  // --- fronteira ---
  dispersao(el('chFront'), frontAtual.map((p, i) => ({
    x: p.vol, y: p.ret, forte: true, destaque: i === Math.min(estado.perfil, frontAtual.length - 1),
    tip: `<b>Carteira ${i + 1}</b>
      <div class="r"><span>Retorno esperado</span><span>${pct(p.ret)}</span></div>
      <div class="r"><span>Volatilidade</span><span>${pct(p.vol)}</span></div>
      <div class="r"><span>Sharpe</span><span>${num((p.ret - rf) / p.vol)}</span></div>`
  })), { fx: v => pct(v, 0), fy: v => pct(v, 0), rotuloX: 'Volatilidade anual',
         rotuloY: 'Retorno esperado anual', altura: 400, linha: true });

  const ctlR = el('ctlR');
  ctlR.max = String(Math.max(frontAtual.length - 1, 0));
  el('lblR').textContent = estado.perfil === 0 ? 'mínimo'
    : `${estado.perfil + 1} de ${frontAtual.length}`;
}

function trocarAba(nome) {
  document.querySelectorAll('.tabs button').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.p === nome)));
  ['carteira', 'ranking', 'fronteira', 'excluidas'].forEach(p =>
    el('p-' + p).classList.toggle('hidden', p !== nome));
  render();
}

function ligarControles() {
  const bind = (id, chave, fn, rotulo) => {
    const c = el(id);
    c.addEventListener('input', () => {
      estado[chave] = fn(c);
      if (rotulo) rotulo();
      render();
    });
  };
  bind('ctlN', 'n', c => +c.value, () => el('lblN').textContent = el('ctlN').value);
  bind('ctlW', 'cap', c => +c.value / 100, () => el('lblW').textContent = el('ctlW').value + '%');
  bind('ctlR', 'perfil', c => +c.value);
  bind('ctlCap', 'capital', c => Math.max(+c.value || 0, 0));
  bind('ctlUnico', 'unico', c => c.checked);
  document.querySelectorAll('.tabs button').forEach(b =>
    b.addEventListener('click', () => trocarAba(b.dataset.p)));
  let t;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 160); });
}

// ===========================================================================
async function iniciar() {
  try {
    const resp = await fetch('dados.json?v=' + Date.now());
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    D = await resp.json();
  } catch (e) {
    el('loading').classList.add('hidden');
    const box = el('erro');
    box.classList.remove('hidden');
    box.innerHTML = `<p><b>Não foi possível carregar os dados.</b></p>
      <p>O arquivo <code>dados.json</code> não foi encontrado. Rode a ação
      <b>Atualizar dados</b> no GitHub para gerá-lo.</p>
      <p class="muted">${e.message}</p>`;
    return;
  }

  idx = new Map(D.empresas.map(e => [e.ticker, e]));
  el('stamp').textContent = D.meta.geradoEm;
  const modo = String(D.meta.diagnostico?.modo || '');
  el('stampFonte').textContent = modo.startsWith('DEMONSTRA')
    ? '⚠ dados sintéticos de demonstração'
    : `${D.empresas.length} empresas no universo`;

  el('tbExc').querySelector('tbody').innerHTML = (D.excluidas || []).map(e =>
    `<tr><td class="l tk">${e.ticker || '—'}</td>
      <td class="l cap" title="${e.nome || ''}">${e.nome || '—'}</td>
      <td class="l cap muted">${e.setor || '—'}</td>
      <td class="l muted">${e.motivo || '—'}</td></tr>`).join('')
    || '<tr><td colspan="4" class="l muted">Nenhuma empresa excluída.</td></tr>';

  const maxN = Math.min(D.empresas.length, 60);
  el('ctlN').max = String(maxN);
  if (estado.n > maxN) { estado.n = maxN; el('ctlN').value = String(maxN); el('lblN').textContent = String(maxN); }

  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  ligarControles();
  render();
}

iniciar();
