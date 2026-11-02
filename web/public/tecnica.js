/* Aba Análise técnica — tela.
 *
 * A conta está toda em tecnica_motor.js (conferido contra tecnica/*.py pelos
 * testes); as métricas do backtest são as da Simulação (simulacao_motor.js).
 * Aqui: carregar a base, desenhar o gráfico de velas e o indicador, o teste
 * da regra e o painel, e guardar as escolhas no endereço.
 */
'use strict';

const PASTA = 'precos/';
const T = TecMotor;
const el = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ===========================================================================
// Formatação (a mesma das outras abas)
// ===========================================================================
const nf = (d = 1) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const ok = (v) => v != null && Number.isFinite(v);
const pct = (v, d = 1) => (ok(v) ? nf(d).format(v * 100) + '%' : '—');
const pctS = (v, d = 1) => (ok(v) ? (v > 0 ? '+' : '') + nf(d).format(v * 100) + '%' : '—');
const num = (v, d = 2) => (ok(v) ? nf(d).format(v) : '—');
const reais = (v) => (ok(v) ? 'R$ ' + nf(2).format(v) : '—');
const dataBR = (s) => (s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : '—');
const dataCurta = (s) => (s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(2, 4) : '—');
const mesBR = (s) => (s ? s.slice(5, 7) + '/' + s.slice(0, 4) : '—');
const cor = (v) => (!ok(v) ? '' : (v > 0 ? 'up' : (v < 0 ? 'down' : '')));
function dinheiro(v) {
  if (!ok(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return 'R$ ' + nf(1).format(v / 1e9) + ' bi';
  if (a >= 1e6) return 'R$ ' + nf(1).format(v / 1e6) + ' mi';
  if (a >= 1e3) return 'R$ ' + nf(0).format(v / 1e3) + ' mil';
  return 'R$ ' + nf(0).format(v);
}

// ===========================================================================
// Estado
// ===========================================================================
const PERIODOS = { '3m': 63, '6m': 126, '1a': 252, '2a': 504, '5a': 1260, max: Infinity };
const MAX_VELAS = 320;            // acima disso, linha de fechamento (vela vira risco)
const SOBRE = [
  { k: 'mm20', nome: 'MM20', cor: '--c4' }, { k: 'mm50', nome: 'MM50', cor: '--s1' },
  { k: 'mm200', nome: 'MM200', cor: '--s2' }, { k: 'mme9', nome: 'MME9', cor: '--c5' },
  { k: 'mme21', nome: 'MME21', cor: '--c7' }, { k: 'bb', nome: 'Bollinger', cor: '--ink-3' },
  { k: 'a52', nome: 'Máx./mín. 52s', cor: '--ink-3' },
];
const FILTROS = [
  ['todos', 'Todas'], ['alta', 'Tendência de alta'], ['cruzouAlta', 'Virou para alta (10 pregões)'],
  ['cruzouBaixa', 'Virou para baixa (10 pregões)'], ['sobrevendido', 'IFR abaixo de 30'],
  ['sobrecomprado', 'IFR acima de 70'], ['max52', 'Na máxima de 52 semanas'], ['min52', 'Na mínima de 52 semanas'],
  ['rompe', 'Rompeu a máxima de 55 pregões'], ['volume', 'Volume 2× a média'], ['fm', 'Na seleção da fórmula mágica'],
];
const estado = {
  t: null, periodo: '1a', osc: 'ifr', sobre: ['mm50', 'mm200'], regra: 'mm',
  params: { ...T.REGRAS.mm.params }, de: null, filtro: 'todos', busca: '', ord: null, dir: -1,
  mostrarOps: true,
};
let BASE = null;     // {indice, pregoes, acoes, porT, ibov, cdi, sinais, fm}
let ATUAL = null;    // {t, prep, ind, resumo, vel}
let BT = null;       // resultado do backtest do papel atual
const cache = new Map();

async function json(caminho, opcional = false) {
  const r = await fetch(caminho, { cache: 'no-cache' });
  if (!r.ok) { if (opcional) return null; throw new Error(`${caminho}: HTTP ${r.status}`); }
  return r.json();
}

// ===========================================================================
// Carga
// ===========================================================================
async function iniciar() {
  let indice;
  try { indice = await json(PASTA + 'indice.json'); }
  catch (e) {
    el('loading').classList.add('hidden');
    el('erro').classList.remove('hidden');
    el('erro').innerHTML = `Não consegui ler a base de preços (<code>precos/indice.json</code>).<br>Rode a ação <b>Atualizar preços</b> no GitHub.`;
    return;
  }
  const [ibovA, cdiA, sinais, dados] = await Promise.all([
    json(PASTA + indice.bench.IBOV.arquivo), json(PASTA + indice.bench.CDI.arquivo),
    json(PASTA + 'ohlc/_sinais.json', true).catch(() => null), json('dados.json', true).catch(() => null),
  ]);
  const pregoes = indice.pregoes;
  const acoes = indice.ativos.filter(a => a.classe === 'acao');
  const fm = {};
  for (const e of (dados && dados.empresas) || []) if (e.ticker) fm[e.ticker] = { rank: e.rank, sel: !!e.selecionada };
  BASE = {
    indice, pregoes, acoes, porT: Object.fromEntries(acoes.map(a => [a.t, a])),
    ibov: T.lerRetornos(ibovA), cdi: T.completarCdi(T.lerRetornos(cdiA), pregoes.length - 1),
    sinais, fm,
  };
  el('stamp').textContent = dataBR(pregoes[pregoes.length - 1]);
  if (indice.demo) el('baseDemo').classList.remove('hidden');
  el('txUniverso').textContent = acoes.length;

  Object.assign(estado, T.decodificar(location.search.slice(1)));
  if (!estado.t || !BASE.porT[estado.t]) {
    estado.t = BASE.porT.PETR4 ? 'PETR4' : acoes.slice().sort((a, b) => (b.liq || 0) - (a.liq || 0))[0].t;
  }
  if (!T.REGRAS[estado.regra]) estado.regra = 'mm';
  if (!estado.params) estado.params = { ...T.REGRAS[estado.regra].params };

  montarControles();
  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  renderPainel();
  await escolher(estado.t, false);
}

async function carregar(t) {
  if (cache.has(t)) return cache.get(t);
  // o painel diz quem tem velas; sem painel, tenta (e um 404 só quer dizer "ainda não")
  const linha = BASE.sinais && BASE.sinais.papeis.find(l => l.t === t);
  const tentarVelas = !linha || linha.velas;
  const [ret, vel] = await Promise.all([json(PASTA + t + '.json'),
    tentarVelas ? json(PASTA + 'ohlc/' + t + '.json', true).catch(() => null) : null]);
  const prep = T.preparar(ret, vel && vel.a ? vel : null, BASE.pregoes);
  const ind = T.indicadores(prep);
  const d = { t, prep, ind, vel, resumo: T.resumo(prep, ind, BASE.ibov, BASE.pregoes) };
  cache.set(t, d);
  return d;
}

async function escolher(t, rolar = true) {
  t = String(t || '').toUpperCase().trim();
  if (!BASE.porT[t]) { el('notaGrafico').textContent = `${t || '—'} não está na base de ações.`; return; }
  estado.t = t;
  el('papel').value = t;
  try { ATUAL = await carregar(t); }
  catch (e) { el('notaGrafico').textContent = `Não consegui ler os preços de ${t} (${e.message}).`; return; }
  el('semVelas').classList.toggle('hidden', !!ATUAL.vel);
  rodarBacktest();
  renderCabecalho(); renderGrafico(); renderBacktest();
  document.querySelectorAll('#tbSinais tbody tr').forEach(tr => tr.classList.toggle('escolhido', tr.dataset.t === t));
  refletir();
  if (rolar) el('secGrafico').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ===========================================================================
// Controles
// ===========================================================================
function montarControles() {
  el('listaPapeis').innerHTML = BASE.acoes.map(a => `<option value="${a.t}">${esc(a.nome)}</option>`).join('');
  el('papel').addEventListener('change', () => escolher(el('papel').value, false));
  el('papel').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') escolher(el('papel').value, false); });

  el('chSobre').innerHTML = SOBRE.map(s => `<button data-v="${s.k}">${s.nome}</button>`).join('');
  el('chSobre').addEventListener('click', (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    const k = b.dataset.v;
    estado.sobre = estado.sobre.includes(k) ? estado.sobre.filter(x => x !== k) : [...estado.sobre, k];
    refletir(); renderGrafico();
  });
  const seg = (id, campo, depois) => el(id).addEventListener('click', (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    estado[campo] = b.dataset.v; refletir(); depois();
  });
  seg('segPeriodo', 'periodo', renderGrafico);
  seg('segOsc', 'osc', renderGrafico);

  el('regra').innerHTML = Object.entries(T.REGRAS).map(([k, r]) => `<option value="${k}">${esc(r.nome)}</option>`).join('');
  el('regra').value = estado.regra;
  el('regra').addEventListener('change', () => {
    estado.regra = el('regra').value;
    estado.params = { ...T.REGRAS[estado.regra].params };
    montarParams(); rodarBacktest(); renderBacktest(); renderGrafico(); refletir();
  });
  montarParams();
  if (estado.de) el('de').value = estado.de;
  el('de').addEventListener('change', () => { estado.de = el('de').value || null; rodarBacktest(); renderBacktest(); renderGrafico(); refletir(); });
  el('mostrarOps').checked = estado.mostrarOps;
  el('mostrarOps').addEventListener('change', () => { estado.mostrarOps = el('mostrarOps').checked; renderGrafico(); });

  el('chFiltro').innerHTML = FILTROS.map(([k, n]) => `<button data-v="${k}">${n}</button>`).join('');
  seg('chFiltro', 'filtro', renderPainel);
  el('busca').addEventListener('input', () => { estado.busca = el('busca').value.trim().toLowerCase(); renderPainel(); });
  el('tbSinais').querySelector('thead').addEventListener('click', (ev) => {
    const th = ev.target.closest('th.ord'); if (!th) return;
    const k = th.dataset.k;
    if (estado.ord === k) estado.dir = -estado.dir; else { estado.ord = k; estado.dir = (k === 't' || k === 'fm') ? 1 : -1; }
    renderPainel();
  });
  el('tbSinais').querySelector('tbody').addEventListener('click', (ev) => {
    const tr = ev.target.closest('tr[data-t]'); if (tr) escolher(tr.dataset.t);
  });
  addEventListener('resize', () => { clearTimeout(montarControles.t); montarControles.t = setTimeout(() => { renderGrafico(); renderBacktest(); }, 150); });
}

const ROTULOS = {
  rapida: 'Rápida', lenta: 'Lenta', tipo: 'Tipo', n: 'Pregões', sinal: 'Sinal',
  baixo: 'Compra abaixo de', alto: 'Vende acima de', k: 'Desvios', entrada: 'Máxima de', saida: 'Sai na mínima de',
};
function montarParams() {
  const p = estado.params;
  el('params').innerHTML = Object.keys(T.REGRAS[estado.regra].params).map(k => k === 'tipo'
    ? `<div class="ctl"><label for="p_${k}">${ROTULOS[k]}</label><select id="p_${k}" data-k="${k}">
         <option value="s"${p[k] === 's' ? ' selected' : ''}>Simples</option><option value="e"${p[k] === 'e' ? ' selected' : ''}>Exponencial</option></select></div>`
    : `<div class="ctl"><label for="p_${k}">${ROTULOS[k]}</label><input type="number" id="p_${k}" data-k="${k}" value="${p[k]}"
         min="${k === 'baixo' || k === 'alto' ? 1 : (k === 'k' ? 0.5 : 2)}" max="${k === 'baixo' || k === 'alto' ? 99 : 400}" step="${k === 'k' ? 0.5 : 1}"></div>`).join('');
  el('params').querySelectorAll('[data-k]').forEach(x => x.addEventListener('change', () => {
    const k = x.dataset.k;
    estado.params[k] = k === 'tipo' ? x.value : +x.value;
    rodarBacktest(); renderBacktest(); renderGrafico(); refletir();
  }));
}

function refletir() {
  const marca = (id, f) => el(id).querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(f(b.dataset.v))));
  marca('segPeriodo', v => v === estado.periodo);
  marca('segOsc', v => v === estado.osc);
  marca('chSobre', v => estado.sobre.includes(v));
  marca('chFiltro', v => v === estado.filtro);
  const qs = T.codificar(estado);
  history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
}

// ===========================================================================
// Cabeçalho do papel
// ===========================================================================
function renderCabecalho() {
  const { t, resumo: r, prep } = ATUAL;
  const a = BASE.porT[t], P = BASE.pregoes;
  const fm = BASE.fm[t];
  const preco = r.preco != null ? reais(r.preco) : '';
  el('cab').innerHTML = `<span class="tkG">${t}</span>
    <span class="px">${preco}</span>
    <span class="${cor(r.var1d)}" style="font-weight:600">${pctS(r.var1d, 2)}</span>
    <span class="nmG">${esc(a.nome)} · fechamento de ${dataBR(r.ate)}${r.atraso > 0 ? ` (${r.atraso} pregões antes do último)` : ''}
      ${fm ? ` · fórmula mágica #${fm.rank}${fm.sel ? ' ✓' : ''}` : ''} · liquidez ${dinheiro(a.liq)}/dia</span>`;
  const tile = (k, v, h = '') => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="h">${h}</div></div>`;
  if (r.parado) {
    el('tiles').innerHTML = tile('Sem cotação', dataBR(r.parado), 'o Yahoo parou de mandar preço');
    return;
  }
  const zona = (v, lo, hi) => (!ok(v) ? '' : v < lo ? 'abaixo de ' + lo : v > hi ? 'acima de ' + hi : 'entre ' + lo + ' e ' + hi);
  el('tiles').innerHTML = [
    tile('Tendência', r.tend ? (r.tend === 'alta' ? '▲ alta' : '▼ baixa') : '—', r.tendDesde ? 'desde ' + dataCurta(r.tendDesde) : 'MM50 × MM200'),
    tile('vs MM200', pctS(r.dMm200), 'distância do preço'),
    tile('IFR 14', num(r.ifr, 0), zona(r.ifr, 30, 70)),
    tile('MACD', r.macdAcima == null ? '—' : (r.macdAcima ? 'acima' : 'abaixo'), r.macdDesde ? 'do sinal desde ' + dataCurta(r.macdDesde) : 'da linha de sinal'),
    tile('ADX 14', num(r.adx, 0), !ok(r.adx) ? 'precisa das velas' : r.adx >= 25 ? 'tendência forte' : 'tendência fraca'),
    tile('ATR 14', pct(r.atrPct, 1), 'amplitude média/dia'),
    tile('vs máx. 52s', pctS(r.dMax52), r.novaMax52 ? 'na máxima hoje' : (ok(r.dMin52) ? pctS(r.dMin52) + ' da mínima' : '')),
    tile('Força rel. 6m', pctS(r.fr6m), 'contra o Ibovespa'),
  ].join('');
}

// ===========================================================================
// Gráfico de preço e do indicador
// ===========================================================================
const NS = 'http://www.w3.org/2000/svg';
const mk = (t, a = {}) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
const tip = el('tip');
function mostrarTip(ev, html) {
  tip.innerHTML = html; tip.style.opacity = '1';
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - r.height - 12;
  if (x + r.width > innerWidth - 10) x = ev.clientX - r.width - 14;
  if (y < 8) y = ev.clientY + 18;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const esconderTip = () => { tip.style.opacity = '0'; };

function escalaNice(lo, hi, passos = 6) {
  const bruto = (hi - lo) / passos || Math.abs(hi) * 0.1 || 1;
  const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 5, 10].map(f => f * mag).find(p => p >= bruto) || bruto;
  return { lo: Math.floor(lo / passo) * passo, hi: Math.ceil(hi / passo) * passo, passo };
}

/** Janela visível em índices do calendário. */
function janela() {
  const { prep } = ATUAL;
  const n = PERIODOS[estado.periodo] || 252;
  const e = prep.fim;
  return { s: Math.max(prep.s0, Number.isFinite(n) ? e - n + 1 : prep.s0), e };
}

function eixoX(svg, m, iw, h, datas, X) {
  const n = datas.length, anos = n > 600;
  let ultimoX = -Infinity;
  for (let i = 1; i < n; i++) {
    const vira = anos ? datas[i].slice(0, 4) !== datas[i - 1].slice(0, 4) : datas[i].slice(0, 7) !== datas[i - 1].slice(0, 7);
    if (!vira || X(i) - ultimoX < 52) continue;
    ultimoX = X(i);
    svg.appendChild(mk('line', { x1: X(i), x2: X(i), y1: m.t, y2: h - m.b, class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: X(i), y: h - m.b + 16, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = anos ? datas[i].slice(0, 4) : mesBR(datas[i]); svg.appendChild(t);
  }
}

function caminho(v, X, Y, de = 0) {
  let d = '', abre = true;
  for (let i = de; i < v.length; i++) {
    if (!ok(v[i])) { abre = true; continue; }
    d += (abre ? 'M' : 'L') + X(i).toFixed(1) + ',' + Y(v[i]).toFixed(1);
    abre = false;
  }
  return d;
}

function renderGrafico() {
  if (!ATUAL) return;
  const { prep, ind } = ATUAL, P = BASE.pregoes;
  const { s, e } = janela();
  const off = s - prep.s0, n = e - s + 1;
  const datas = P.slice(s, e + 1);
  const pega = (v) => (v ? v.subarray(off, off + n) : null);
  const C = pega(prep.c), O = pega(prep.o), H = pega(prep.h), L = pega(prep.l), V = pega(prep.vol);
  const temVela = ATUAL.vel && prep.temVela.subarray(off, off + n).some(x => x);
  const velas = temVela && n <= MAX_VELAS;
  const notas = [];

  // ---------- preço ----------
  const svg = el('grPreco');
  svg.textContent = '';
  const w = svg.clientWidth || svg.parentNode.clientWidth || 800;
  const h = Math.max(300, Math.min(440, Math.round(w * 0.46)));
  const m = { t: 10, r: 62, b: 26, l: 8 };
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('height', h);
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const ihPreco = ih * 0.8;
  const X = (i) => m.l + (n > 1 ? (i + 0.5) / n : 0.5) * iw;
  const sobre = [];
  for (const sb of SOBRE) {
    if (!estado.sobre.includes(sb.k)) continue;
    if (sb.k === 'bb') sobre.push({ ...sb, v: [pega(ind.bbSup), pega(ind.bbInf)], meio: pega(ind.bbMeio) });
    else if (sb.k === 'a52') sobre.push({ ...sb, v: [pega(ind.max52), pega(ind.min52)] });
    else sobre.push({ ...sb, v: [pega(ind[sb.k])] });
  }
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < n; i++) {
    const a = velas ? L[i] : C[i], b = velas ? H[i] : C[i];
    if (ok(a) && a < lo) lo = a; if (ok(b) && b > hi) hi = b;
  }
  for (const sb of sobre) for (const v of sb.v) for (let i = 0; i < n; i++) if (ok(v[i])) { lo = Math.min(lo, v[i]); hi = Math.max(hi, v[i]); }
  const folga = (hi - lo) * 0.04 || hi * 0.02;
  const esY = escalaNice(lo - folga, hi + folga, 6);
  const Y = (v) => m.t + ihPreco - ((v - esY.lo) / (esY.hi - esY.lo)) * ihPreco;
  const casas = esY.passo < 0.1 ? 2 : esY.passo < 1 ? 2 : 0;
  for (let v = esY.lo; v <= esY.hi + esY.passo / 2; v += esY.passo) {
    if (Y(v) < m.t - 1 || Y(v) > m.t + ihPreco + 1) continue;
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v), class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: m.l + iw + 6, y: Y(v) + 4, 'font-size': 11 });
    t.textContent = nf(casas).format(v); svg.appendChild(t);
  }
  eixoX(svg, m, iw, h, datas, X);

  // lacunas (preço parado do Yahoo) em cinza
  for (const [a, c] of prep.lacunas) {
    const i0 = Math.max(a, s) - s, i1 = Math.min(c - 1, e) - s;
    if (i1 < i0) continue;
    svg.appendChild(mk('rect', { x: X(i0) - iw / n / 2, y: m.t, width: Math.max(2, X(i1) - X(i0) + iw / n), height: ih,
      fill: css('--ink-3'), opacity: 0.14 }));
    notas.push(`Faixa cinza: o Yahoo ficou sem cotação de ${dataBR(P[a])} a ${dataBR(P[c - 1])}; os indicadores recomeçam depois.`);
  }

  // volume no rodapé do gráfico de preço
  if (temVela) {
    let vmax = 0;
    for (let i = 0; i < n; i++) if (ok(V[i]) && V[i] > vmax) vmax = V[i];
    const yb = m.t + ih, hv = ih * 0.17;
    const larg = Math.max(1, iw / n * 0.72);
    for (let i = 0; i < n; i++) {
      if (!ok(V[i]) || V[i] <= 0 || vmax <= 0) continue;
      const alt = V[i] / vmax * hv;
      const sobe = C[i] >= (velas ? O[i] : (i ? C[i - 1] : C[i]));
      svg.appendChild(mk('rect', { x: X(i) - larg / 2, y: yb - alt, width: larg, height: alt,
        fill: css(sobe ? '--good' : '--bad'), opacity: 0.32 }));
    }
  }

  // Bollinger: faixa
  for (const sb of sobre.filter(x => x.k === 'bb')) {
    let d = '';
    const [sup, inf] = sb.v;
    const idx = [];
    for (let i = 0; i < n; i++) if (ok(sup[i])) idx.push(i);
    if (idx.length) {
      d = idx.map((i, j) => (j ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(sup[i]).toFixed(1)).join('') +
          idx.slice().reverse().map(i => 'L' + X(i).toFixed(1) + ',' + Y(inf[i]).toFixed(1)).join('') + 'Z';
      svg.appendChild(mk('path', { d, fill: css('--s1'), opacity: 0.07, stroke: 'none' }));
      for (const v of sb.v) svg.appendChild(mk('path', { d: caminho(v, X, Y), fill: 'none', stroke: css('--ink-3'), 'stroke-width': 1 }));
      svg.appendChild(mk('path', { d: caminho(sb.meio, X, Y), fill: 'none', stroke: css('--ink-3'), 'stroke-width': 1, 'stroke-dasharray': '3 3' }));
    }
  }

  // preço
  if (velas) {
    const larg = Math.max(1, Math.min(11, iw / n * 0.7));
    for (let i = 0; i < n; i++) {
      if (!ok(C[i])) continue;
      const sobe = C[i] >= O[i], c_ = css(sobe ? '--good' : '--bad');
      svg.appendChild(mk('line', { x1: X(i), x2: X(i), y1: Y(H[i]), y2: Y(L[i]), stroke: c_, 'stroke-width': 1 }));
      const y1 = Y(Math.max(O[i], C[i])), y2 = Y(Math.min(O[i], C[i]));
      svg.appendChild(mk('rect', { x: X(i) - larg / 2, y: y1, width: larg, height: Math.max(1, y2 - y1), fill: c_ }));
    }
  } else {
    svg.appendChild(mk('path', { d: caminho(C, X, Y), fill: 'none', stroke: css('--ink'), 'stroke-width': 1.5, 'stroke-linejoin': 'round' }));
    if (temVela) notas.push(`Com mais de ${MAX_VELAS} pregões na tela, o preço vai em linha de fechamento: as velas viram riscos.`);
  }
  for (const sb of sobre.filter(x => x.k !== 'bb')) {
    for (const v of sb.v) svg.appendChild(mk('path', { d: caminho(v, X, Y), fill: 'none', stroke: css(sb.cor),
      'stroke-width': sb.k === 'a52' ? 1 : 1.6, ...(sb.k === 'a52' ? { 'stroke-dasharray': '5 4' } : {}) }));
  }

  // operações do teste
  if (estado.mostrarOps && BT) {
    for (const op of BT.ops) {
      const marca = (j, compra) => {
        const i = j - s;
        if (i < 0 || i >= n) return;
        const y = compra ? Y(velas ? L[i] : C[i]) + 12 : Y(velas ? H[i] : C[i]) - 12;
        const d = compra ? `M${X(i)},${y - 6}l5,8h-10z` : `M${X(i)},${y + 6}l5,-8h-10z`;
        svg.appendChild(mk('path', { d, fill: css(compra ? '--s1' : '--s2') }));
      };
      marca(op.entrada, true);
      if (!op.aberta) marca(op.saida, false);
    }
  }

  // legenda com o último valor
  const ult = (v) => { for (let i = v.length - 1; i >= 0; i--) if (ok(v[i])) return v[i]; return null; };
  el('legPreco').innerHTML = [
    `<span><i class="linha" style="background:${css('--ink')}"></i>Fechamento${prep.emReais ? '' : ' (base 100)'} <b>${num(C[n - 1])}</b></span>`,
    ...sobre.map(sb => sb.k === 'bb' ? `<span><i class="banda" style="background:${css('--s1')}"></i>Bollinger 20, 2 <b>${num(ult(sb.v[1]))} – ${num(ult(sb.v[0]))}</b></span>`
      : sb.k === 'a52' ? `<span><i class="trac" style="color:${css('--ink-3')}"></i>Máx./mín. 52 semanas <b>${num(ult(sb.v[1]))} – ${num(ult(sb.v[0]))}</b></span>`
      : `<span><i class="linha" style="background:${css(sb.cor)}"></i>${sb.nome} <b>${num(ult(sb.v[0]))}</b></span>`),
    ...(estado.mostrarOps && BT && BT.ops.length ? [`<span><i style="background:${css('--s1')}"></i>compra</span><span><i style="background:${css('--s2')}"></i>venda</span>`] : []),
  ].join('');

  // ---------- indicador ----------
  const osc = desenharOsc(s, e, n, off, X, m, iw, w);

  if (!prep.emReais) notas.push('Sem o fechamento de hoje em reais ainda: o gráfico está em base 100 no último pregão.');
  if (prep.s0 > s) notas.push(`Primeiro preço da base: ${dataBR(P[prep.s0])}.`);
  el('notaGrafico').textContent = [...new Set(notas)].join(' ');

  // ---------- cursor comum aos dois gráficos ----------
  const cursores = [svg, el('grOsc')].map(sv => {
    const c = mk('line', { y1: 0, y2: sv === svg ? h - m.b : osc.h - osc.m.b, class: 'gridline', 'stroke-width': 1, opacity: 0 });
    sv.appendChild(c); return c;
  });
  const conteudo = (i) => {
    const j = i + off, d = datas[i];
    let html = `<b>${dataBR(d)}</b>`;
    const lin = (k, v) => `<div class="r"><span>${k}</span><span>${v}</span></div>`;
    if (velas || temVela) html += lin('Abertura', num(O[i])) + lin('Máxima', num(H[i])) + lin('Mínima', num(L[i]));
    html += lin('Fechamento', num(C[i]));
    if (j > 0) html += lin('No dia', pctS(prep.c[j] / prep.c[j - 1] - 1, 2));
    if (temVela && ok(V[i])) html += lin('Volume', dinheiro(V[i]));
    for (const sb of sobre) {
      if (sb.k === 'bb') html += lin('Bollinger', `${num(sb.v[1][i])} – ${num(sb.v[0][i])}`);
      else if (sb.k === 'a52') html += lin('52 semanas', `${num(sb.v[1][i])} – ${num(sb.v[0][i])}`);
      else html += lin(sb.nome, num(sb.v[0][i]));
    }
    html += osc.tip(i);
    return html;
  };
  for (const sv of [svg, el('grOsc')]) {
    const ehPreco = sv === svg;
    const alvo = mk('rect', { x: m.l, y: 0, width: iw, height: ehPreco ? h : osc.h, fill: 'transparent' });
    alvo.addEventListener('mousemove', (ev) => {
      const larg = sv.clientWidth || w;
      const cx = ev.offsetX * (w / larg);
      const i = Math.max(0, Math.min(n - 1, Math.floor(((cx - m.l) / iw) * n)));
      for (const c of cursores) { c.setAttribute('x1', X(i)); c.setAttribute('x2', X(i)); c.setAttribute('opacity', 1); }
      mostrarTip(ev, conteudo(i));
    });
    alvo.addEventListener('mouseleave', () => { cursores.forEach(c => c.setAttribute('opacity', 0)); esconderTip(); });
    sv.appendChild(alvo);
  }
}

function desenharOsc(s, e, n, off, X, m0, iw, w) {
  const { prep, ind } = ATUAL;
  const svg = el('grOsc');
  svg.textContent = '';
  const h = 150, m = { t: 8, r: m0.r, b: 22, l: m0.l };
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('height', h);
  const ih = h - m.t - m.b;
  const pega = (v) => v.subarray(off, off + n);
  const temVela = !!ATUAL.vel;
  let linhas = [], barras = null, refs = [], faixa = null, fmt = (v) => num(v, 0), nome = '', aviso = '';
  const o = estado.osc;
  if (o === 'ifr') {
    nome = 'IFR 14'; linhas = [{ v: pega(ind.ifr), cor: '--s1', nome: 'IFR' }]; refs = [30, 70]; faixa = [0, 100];
  } else if (o === 'macd') {
    nome = 'MACD 12, 26, 9'; fmt = (v) => num(v, 2);
    linhas = [{ v: pega(ind.macd), cor: '--s1', nome: 'MACD' }, { v: pega(ind.macdSinal), cor: '--s2', nome: 'Sinal' }];
    barras = { v: pega(ind.macdHist), nome: 'Histograma' }; refs = [0];
  } else if (o === 'est') {
    nome = 'Estocástico lento 14, 3, 3'; refs = [20, 80]; faixa = [0, 100];
    linhas = [{ v: pega(ind.estK), cor: '--s1', nome: '%K' }, { v: pega(ind.estD), cor: '--s2', nome: '%D' }];
    if (!temVela) aviso = 'precisa da máxima e da mínima do dia (velas)';
  } else if (o === 'adx') {
    nome = 'ADX 14'; refs = [25];
    linhas = [{ v: pega(ind.adx), cor: '--ink', nome: 'ADX' }, { v: pega(ind.diMais), cor: '--good', nome: '+DI' }, { v: pega(ind.diMenos), cor: '--bad', nome: '−DI' }];
    if (!temVela) aviso = 'precisa da máxima e da mínima do dia (velas)';
  } else if (o === 'obv') {
    nome = 'OBV (volume financeiro acumulado)'; fmt = dinheiro;
    const v = pega(ind.obv), base = new Float64Array(n);
    let b0 = null;
    for (let i = 0; i < n; i++) { if (b0 == null && ok(v[i])) b0 = v[i]; base[i] = ok(v[i]) && b0 != null ? v[i] - b0 : NaN; }
    linhas = [{ v: base, cor: '--s1', nome: 'OBV' }]; refs = [0];
    if (!temVela) aviso = 'precisa do volume (velas)';
  } else {
    nome = 'Força relativa: preço ÷ Ibovespa, base 100'; fmt = (v) => num(v, 1);
    const c = pega(prep.c), out = new Float64Array(n).fill(NaN), ib = BASE.ibov;
    let acc = 1;
    for (let i = 0; i < n; i++) {
      const j = s + i;
      if (i > 0) { const k = j - ib.i0; acc *= 1 + (k >= 0 && k < ib.r.length ? ib.r[k] : 0); }
      out[i] = 100 * (c[i] / c[0]) / acc;
    }
    linhas = [{ v: out, cor: '--s1', nome: 'Força relativa' }]; refs = [100];
  }
  if (aviso) linhas = [];
  let lo = Infinity, hi = -Infinity;
  for (const l of [...linhas, ...(barras ? [barras] : [])]) for (const v of l.v) if (ok(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  for (const r of refs) { lo = Math.min(lo, r); hi = Math.max(hi, r); }
  if (faixa) { lo = faixa[0]; hi = faixa[1]; }
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  if (hi === lo) hi = lo + 1;
  const Y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
  if (faixa && refs.length === 2) {
    svg.appendChild(mk('rect', { x: m.l, y: Y(refs[1]), width: iw, height: Y(refs[0]) - Y(refs[1]), fill: css('--s1'), opacity: 0.05 }));
  }
  for (const r of refs) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: Y(r), y2: Y(r), stroke: css('--line-strong'), 'stroke-dasharray': '4 3' }));
    const t = mk('text', { x: m.l + iw + 6, y: Y(r) + 4, 'font-size': 11 }); t.textContent = fmt(r); svg.appendChild(t);
  }
  if (!faixa && linhas.length) {
    for (const v of [hi, lo]) { const t = mk('text', { x: m.l + iw + 6, y: Y(v) + (v === hi ? 10 : -2), 'font-size': 10.5 }); t.textContent = fmt(v); svg.appendChild(t); }
  }
  eixoX(svg, m, iw, h, BASE.pregoes.slice(s, e + 1), X);
  if (barras && linhas.length) {
    const larg = Math.max(1, iw / n * 0.7);
    for (let i = 0; i < n; i++) {
      const v = barras.v[i]; if (!ok(v)) continue;
      const y0 = Y(0), y1 = Y(v);
      svg.appendChild(mk('rect', { x: X(i) - larg / 2, y: Math.min(y0, y1), width: larg, height: Math.max(0.5, Math.abs(y1 - y0)),
        fill: css(v >= 0 ? '--good' : '--bad'), opacity: 0.45 }));
    }
  }
  for (const l of linhas) svg.appendChild(mk('path', { d: caminho(l.v, X, Y), fill: 'none', stroke: css(l.cor), 'stroke-width': 1.5 }));
  if (aviso) {
    const t = mk('text', { x: m.l + iw / 2, y: m.t + ih / 2, 'text-anchor': 'middle', 'font-size': 12.5 });
    t.textContent = nome + ': ' + aviso; svg.appendChild(t);
  }
  const ult = (v) => { for (let i = v.length - 1; i >= 0; i--) if (ok(v[i])) return v[i]; return null; };
  el('legOsc').innerHTML = `<b style="color:var(--ink)">${nome}</b> ` + linhas.map(l =>
    `<span style="margin-left:10px"><i style="display:inline-block;width:12px;height:3px;border-radius:2px;background:${css(l.cor)};vertical-align:middle;margin-right:4px"></i>${l.nome} ${fmt(ult(l.v))}</span>`).join('');
  return {
    h, m,
    tip: (i) => linhas.map(l => `<div class="r"><span>${l.nome}</span><span>${fmt(l.v[i])}</span></div>`).join('') +
      (barras && linhas.length ? `<div class="r"><span>${barras.nome}</span><span>${fmt(barras.v[i])}</span></div>` : ''),
  };
}

// ===========================================================================
// Backtest
// ===========================================================================
function rodarBacktest() {
  BT = null;
  if (!ATUAL) return;
  const ini = estado.de ? T.buscar(BASE.pregoes, estado.de) : null;
  BT = T.simular(ATUAL.prep, estado.regra, estado.params, BASE.cdi, { ini });
}

function textoRegra() {
  const p = estado.params, tipo = p.tipo === 'e' ? 'exponencial' : 'simples';
  switch (estado.regra) {
    case 'mm': return `Comprado enquanto a média ${tipo} de ${p.rapida} pregões está acima da de ${p.lenta}; fora (no CDI) quando está abaixo.`;
    case 'preco_mm': return `Comprado enquanto o fechamento está acima da média ${tipo} de ${p.n} pregões.`;
    case 'macd': return `Comprado enquanto o MACD (${p.rapida}, ${p.lenta}) está acima da sua média de ${p.sinal}.`;
    case 'ifr': return `Compra quando o IFR de ${p.n} fecha abaixo de ${p.baixo} (sobrevendido) e vende quando fecha acima de ${p.alto} (sobrecomprado). Entre um e outro, mantém.`;
    case 'bollinger': return `Compra quando o fechamento fica abaixo da banda de baixo (${p.n} pregões, ${num(+p.k, 1)} desvios) e vende quando volta acima da média.`;
    case 'rompimento': return `Compra quando o fechamento passa da máxima dos ${p.entrada} pregões anteriores; vende quando cai abaixo da mínima dos ${p.saida} anteriores (as "tartarugas").`;
  }
  return '';
}

function curva(r) {
  const out = new Float64Array(r.length + 1); out[0] = 0;
  let acc = 1;
  for (let i = 0; i < r.length; i++) { acc *= 1 + r[i]; out[i + 1] = acc - 1; }
  return out;
}

function renderBacktest() {
  el('regraTxt').textContent = textoRegra();
  const P = BASE.pregoes;
  const svg = el('grBt');
  svg.textContent = '';
  if (!BT) {
    el('tbBt').innerHTML = ''; el('tbOps').innerHTML = ''; el('legBt').innerHTML = '';
    el('notaBt').textContent = ATUAL && ATUAL.resumo.parado
      ? 'O Yahoo parou de mandar preço desta ação: não há trecho limpo para testar.'
      : 'Histórico curto demais para esta regra (a média mais longa ainda não existe no período).';
    return;
  }
  const { s, e, rp, bh } = BT;
  const datas = P.slice(s + 1, e + 1);
  const n = rp.length;
  const rb = new Float64Array(n), rc = new Float64Array(n);
  for (let k = 0; k < n; k++) {
    const j = s + 1 + k;
    const ib = j - BASE.ibov.i0, cd = j - BASE.cdi.i0;
    rb[k] = ib >= 0 && ib < BASE.ibov.r.length ? BASE.ibov.r[ib] : 0;
    rc[k] = cd >= 0 && cd < BASE.cdi.r.length ? BASE.cdi.r[cd] : 0;
  }
  const mt = Motor.metricas(rp, rb, rc, datas, { leve: true });
  const mb = Motor.metricas(bh, rb, rc, datas, { leve: true });
  const mc = Motor.metricas(rc, rb, rc, datas, { leve: true });
  const mi = Motor.metricas(rb, rb, rc, datas, { leve: true });
  const ro = T.resumoOperacoes(BT.ops);

  // gráfico do patrimônio
  const dt = P.slice(s, e + 1);
  const series = [
    { nome: 'CDI', cor: css('--ink-3'), v: curva(rc), tracejado: true, fino: true },
    { nome: 'Ibovespa', cor: css('--ink-2'), v: curva(rb), fino: true },
    { nome: 'Comprar e segurar', cor: css('--s2'), v: curva(bh) },
    { nome: 'Regra', cor: css('--s1'), v: curva(rp) },
  ];
  linhasBt(svg, dt, series);
  el('legBt').innerHTML = series.slice().reverse().map(x =>
    `<span><i class="${x.tracejado ? 'trac' : 'linha'}" style="${x.tracejado ? 'color' : 'background'}:${x.cor}"></i>${x.nome} <b>${pctS(x.v[x.v.length - 1], 0)}</b></span>`).join('');

  const melhor = (a, b, maior = true) => (ok(a) && ok(b) && (maior ? a > b : a < b) ? ' class="num melhor"' : ' class="num"');
  const linha = (rot, a, b, c, f, maior = true, tit = '') =>
    `<tr${tit ? ` title="${esc(tit)}"` : ''}><td class="l">${rot}</td><td${melhor(a, b, maior)}>${f(a)}</td><td${melhor(b, a, maior)}>${f(b)}</td><td class="num muted">${c == null ? '' : f(c)}</td></tr>`;
  el('tbBt').innerHTML = `<thead><tr><th class="l"></th><th>Regra</th><th>Comprar e segurar</th><th>CDI</th></tr></thead><tbody>
    ${linha('Retorno no período', mt.total, mb.total, mc.total, (v) => pctS(v, 0))}
    ${linha('Retorno ao ano', mt.anual, mb.anual, mc.anual, (v) => pctS(v, 1))}
    ${linha('Volatilidade ao ano', mt.vol, mb.vol, null, (v) => pct(v, 1), false)}
    ${linha('Sharpe', mt.sharpe, mb.sharpe, null, (v) => num(v, 2), true, '(retorno ao ano − CDI ao ano) ÷ volatilidade')}
    ${linha('Queda máxima', mt.mdd, mb.mdd, null, (v) => pct(v, 1), true, 'Maior queda do pico ao vale')}
    <tr><td class="l">Tempo comprado</td><td class="num">${pct(BT.exposto, 0)}</td><td class="num">100%</td><td></td></tr>
    <tr><td class="l">Operações</td><td class="num">${ro.n}</td><td class="num">1</td><td></td></tr>
    <tr title="Operações que terminaram com ganho, já descontado o custo"><td class="l">Acerto</td><td class="num">${pct(ro.acerto, 0)}</td><td></td><td></td></tr>
    <tr><td class="l">Ganho médio / perda média</td><td class="num">${pctS(ro.ganhoMedio)} / ${pctS(ro.perdaMedia)}</td><td></td><td></td></tr>
    <tr><td class="l">Duração média</td><td class="num">${ok(ro.duracao) ? nf(0).format(ro.duracao) + ' pregões' : '—'}</td><td></td><td></td></tr>
    </tbody>`;
  el('tbOps').innerHTML = `<thead><tr><th class="l">Compra</th><th class="l">Venda</th><th>Pregões</th><th>Resultado</th></tr></thead><tbody>` +
    (BT.ops.slice().reverse().map(o => `<tr><td class="l">${dataBR(P[o.entrada])}</td><td class="l">${o.aberta ? '<span class="muted">em aberto</span>' : dataBR(P[o.saida])}</td>
      <td class="num">${o.pregoes}</td><td class="num ${cor(o.ret)}">${pctS(o.ret)}</td></tr>`).join('') ||
      `<tr><td colspan="4" class="vazio">A regra não comprou nenhuma vez no período.</td></tr>`) + '</tbody>';

  const notas = [`Período testado: ${dataBR(P[s])} a ${dataBR(P[e])} (${nf(1).format(n / 252)} anos).`];
  if (s > BT.ini) notas.push(`Começa em ${dataBR(P[s])} porque é o primeiro fechamento com a regra calculável (aquecimento dos indicadores desde ${dataBR(P[BT.ini])}).`);
  const pedido = estado.de ? T.buscar(P, estado.de) : ATUAL.prep.s0;
  if (BT.ini > pedido) notas.push(`O Yahoo ficou sem cotação antes de ${dataBR(P[BT.ini])}: o teste só roda no trecho limpo mais recente.`);
  if (!ATUAL.vel) notas.push('Sem as velas ainda, a abertura é tomada igual ao fechamento: a ordem sai um dia depois (o lado conservador).');
  notas.push(`Ibovespa no mesmo período: ${pctS(mi.anual, 1)} ao ano.`);
  el('notaBt').textContent = notas.join(' ');
}

function linhasBt(svg, datas, series) {
  const w = svg.clientWidth || svg.parentNode.clientWidth || 640, h = 300;
  const m = { t: 10, r: 14, b: 26, l: 54 };
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('height', h);
  const iw = w - m.l - m.r, ih = h - m.t - m.b, n = datas.length;
  // escala logarítmica do patrimônio: 16 anos de CDI e de ação no mesmo eixo
  const todos = series.flatMap(s => Array.from(s.v)).filter(ok).map(v => Math.log(1 + v));
  if (!todos.length) return;
  let lo = Math.min(0, ...todos), hi = Math.max(0, ...todos);
  if (hi - lo < 0.05) { hi += 0.03; lo -= 0.03; }
  const X = (i) => m.l + (i / Math.max(n - 1, 1)) * iw;
  const Y = (v) => m.t + ih - ((Math.log(1 + v) - lo) / (hi - lo)) * ih;
  const marcas = [-0.9, -0.75, -0.5, -0.25, 0, 0.5, 1, 2, 4, 9, 19, 49, 99].filter(v => Math.log(1 + v) >= lo - 0.01 && Math.log(1 + v) <= hi + 0.01);
  for (const v of marcas) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v), class: 'gridline', 'stroke-width': 1,
      ...(v === 0 ? { stroke: css('--line-strong') } : {}) }));
    const t = mk('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = (v > 0 ? '+' : '') + nf(0).format(v * 100) + '%'; svg.appendChild(t);
  }
  eixoX(svg, m, iw, h, datas, X);
  for (const s of series) svg.appendChild(mk('path', { d: caminho(s.v, X, Y), fill: 'none', stroke: s.cor,
    'stroke-width': s.fino ? 1.4 : 2, 'stroke-linejoin': 'round', ...(s.tracejado ? { 'stroke-dasharray': '5 4' } : {}) }));
  const cursor = mk('line', { y1: m.t, y2: m.t + ih, class: 'gridline', 'stroke-width': 1, opacity: 0 });
  svg.appendChild(cursor);
  const alvo = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  alvo.addEventListener('mousemove', (ev) => {
    const cx = ev.offsetX * (w / (svg.clientWidth || w));
    const i = Math.max(0, Math.min(n - 1, Math.round(((cx - m.l) / iw) * (n - 1))));
    cursor.setAttribute('x1', X(i)); cursor.setAttribute('x2', X(i)); cursor.setAttribute('opacity', 1);
    mostrarTip(ev, `<b>${dataBR(datas[i])}</b>` + series.slice().reverse().map(s =>
      `<div class="r"><span><i style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${s.cor};vertical-align:middle;margin-right:5px"></i>${s.nome}</span><span>${pctS(s.v[i])}</span></div>`).join(''));
  });
  alvo.addEventListener('mouseleave', () => { cursor.setAttribute('opacity', 0); esconderTip(); });
  svg.appendChild(alvo);
}

// ===========================================================================
// Painel de sinais
// ===========================================================================
function pregoesDesde(data) {
  if (!data) return Infinity;
  const P = BASE.pregoes;
  return P.length - 1 - T.buscar(P, data);
}

function filtrar(l) {
  switch (estado.filtro) {
    case 'alta': return l.tend === 'alta';
    case 'cruzouAlta': return l.tend === 'alta' && pregoesDesde(l.tendDesde) < 10;
    case 'cruzouBaixa': return l.tend === 'baixa' && pregoesDesde(l.tendDesde) < 10;
    case 'sobrevendido': return ok(l.ifr) && l.ifr < 30;
    case 'sobrecomprado': return ok(l.ifr) && l.ifr > 70;
    case 'max52': return !!l.novaMax52;
    case 'min52': return !!l.novaMin52;
    case 'rompe': return !!l.rompe55;
    case 'volume': return ok(l.volRel) && l.volRel >= 2;
    case 'fm': return !!(BASE.fm[l.t] && BASE.fm[l.t].sel);
  }
  return true;
}

function valor(l, k) {
  if (k === 'tend') return l.tend == null ? null : (l.tend === 'alta' ? 1 : 0) * 1e6 - pregoesDesde(l.tendDesde);
  if (k === 'macdAcima') return l.macdAcima == null ? null : (l.macdAcima ? 1 : 0) * 1e6 - pregoesDesde(l.macdDesde);
  if (k === 'fm') return BASE.fm[l.t] ? BASE.fm[l.t].rank : null;
  return l[k];
}

function renderPainel() {
  const S = BASE.sinais;
  if (!S) {
    el('tbSinais').querySelector('tbody').innerHTML = `<tr><td colspan="16" class="vazio">O painel ainda não foi gerado. Ele sai na próxima execução do robô <b>Atualizar preços</b>.</td></tr>`;
    el('contagem').textContent = '';
    refletir();
    return;
  }
  const todos = S.papeis.filter(l => !l.parado && l.atraso <= 5);
  const fora = S.papeis.filter(l => l.parado || l.atraso > 5);
  const b = estado.busca;
  let ls = todos.filter(l => filtrar(l) && (!b || (l.t + ' ' + l.nome).toLowerCase().includes(b)));
  if (estado.ord) {
    const k = estado.ord, d = estado.dir;
    ls.sort((x, y) => {
      const a = valor(x, k), c = valor(y, k);
      if (k === 't') return d * (a < c ? -1 : 1);
      if (!ok(a) && !ok(c)) return 0;
      if (!ok(a)) return 1; if (!ok(c)) return -1;
      return d * (a - c);
    });
  } else ls.sort((x, y) => (y.liq || 0) - (x.liq || 0));
  el('tbSinais').querySelectorAll('th.ord').forEach(th => {
    if (th.dataset.k === estado.ord) th.dataset.dir = estado.dir > 0 ? 'asc' : 'desc'; else delete th.dataset.dir;
  });
  const celR = (v, cls = '') => `<td class="num ${cls} ${cor(v)}">${pctS(v)}</td>`;
  const zona = (v, lo, hi, d = 0) => `<span class="zona ${!ok(v) ? '' : v < lo ? 'baixo' : v > hi ? 'alto' : ''}">${num(v, d)}</span>`;
  el('tbSinais').querySelector('tbody').innerHTML = ls.map(l => {
    const fm = BASE.fm[l.t];
    const recente = (d) => pregoesDesde(d) < 10;
    const tend = l.tend == null ? '—' : `<span class="${l.tend === 'alta' ? 'up' : 'down'}">${l.tend === 'alta' ? '▲ alta' : '▼ baixa'}</span>` +
      (l.tendDesde ? `<small${recente(l.tendDesde) ? ' style="color:var(--ink);font-weight:600"' : ''}>desde ${dataCurta(l.tendDesde)}</small>` : '');
    const md = l.macdAcima == null ? '—' : (l.macdAcima ? 'acima' : 'abaixo') + (l.macdDesde ? `<small>${dataCurta(l.macdDesde)}</small>` : '');
    const alertas = [];
    if (l.desde) alertas.push(`dados limpos só desde ${dataBR(l.desde)} (lacuna do Yahoo antes)`);
    if (l.atraso > 0) alertas.push(`último preço em ${dataBR(l.ate)}`);
    return `<tr data-t="${l.t}" class="${l.t === estado.t ? 'escolhido' : ''}">
      <td class="l"><span class="tk">${l.t}</span>${alertas.length ? ` <span class="muted" title="${esc(alertas.join('; '))}">ⓘ</span>` : ''}
        <div class="nm2" title="${esc(l.nome)}">${esc(l.nome)}</div></td>
      <td class="num">${l.preco != null ? num(l.preco) : '—'}</td>
      ${celR(l.var1d)}${celR(l.r1m, 'opc')}${celR(l.r12m)}
      <td class="l grp estado">${tend}</td>
      ${celR(l.dMm200)}
      <td class="l estado">${md}</td>
      <td class="num grp">${zona(l.ifr, 30, 70)}</td>
      <td class="num opc">${num(l.pctB, 2)}</td>
      <td class="num opc">${zona(l.estK, 20, 80)}</td>
      <td class="num opc">${num(l.adx, 0)}</td>
      <td class="num grp ${l.novaMax52 ? 'up' : ''}">${l.novaMax52 ? 'na máxima' : pctS(l.dMax52)}</td>
      ${celR(l.fr6m)}
      <td class="num opc">${ok(l.volRel) ? nf(1).format(l.volRel) + '×' : '—'}</td>
      <td class="num opc"><span class="fm${fm && fm.sel ? ' ok' : ''}">${fm ? '#' + fm.rank + (fm.sel ? ' ✓' : '') : ''}</span></td>
    </tr>`;
  }).join('') || `<tr><td colspan="16" class="vazio">Nenhuma ação com esse filtro hoje.</td></tr>`;
  el('contagem').innerHTML = `<b>${ls.length}</b> de ${todos.length} ações · fechamento de ${dataBR(S.pregao)}` +
    (S.comVelas < todos.length ? ` · ${S.comVelas} com velas (sem elas, estocástico, ADX e volume ficam vazios)` : '');
  el('stampBase').textContent = `${todos.length} ações no painel`;
  el('rodapeSinais').textContent = fora.length
    ? `Fora do painel, sem cotação recente: ${fora.map(l => `${l.t} (${dataBR(l.parado || l.ate)})`).join(', ')}.` : '';
  const comLac = todos.filter(l => l.desde);
  el('txLacunas').textContent = comLac.length ? `Hoje, com lacuna no histórico: ${comLac.map(l => `${l.t} (limpo desde ${mesBR(l.desde)})`).join(', ')}.` : '';
  refletir();
}

iniciar();
