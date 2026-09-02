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
  for (let k = 0; k < 50; k++) {   // 50 passos ~ 1e-13; 80 era desperdício
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
function fronteira(S, mu, cap, pontos = 20, nLambdas = 60, iteracoes = 900) {
  const escala = Math.max(...mu.map(Math.abs)) || 1;
  const lambdas = [0];
  const passoL = Math.pow(1.28, 60 / nLambdas);
  for (let k = 0; k < nLambdas; k++) lambdas.push(Math.pow(passoL, k) * 1e-3 / escala);

  const bruto = [];
  for (const lam of lambdas) {
    const w = otimizar(S, mu, cap, lam, iteracoes);
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
// Estimadores — portados de magicb3/optimizer.py e conferidos contra ele
// ===========================================================================
const DIAS_ANO = 252;

/** Covariância com encolhimento de Ledoit-Wolf, alvo de correlação constante.
 *  A covariância amostral de 252 dias para 30 ativos é ruidosa demais e produz
 *  pesos instáveis; o encolhimento puxa as correlações para a média. */
function covLedoitWolf(X) {
  const n = X.length, p = X[0].length;
  const media = new Float64Array(p);
  for (const linha of X) for (let j = 0; j < p; j++) media[j] += linha[j] / n;
  const Xc = X.map(l => l.map((v, j) => v - media[j]));

  const S = Array.from({ length: p }, () => new Float64Array(p));
  for (const l of Xc)
    for (let i = 0; i < p; i++)
      for (let j = i; j < p; j++) { const v = l[i] * l[j] / n; S[i][j] += v; if (i !== j) S[j][i] += v; }

  const varr = new Float64Array(p), std = new Float64Array(p);
  for (let i = 0; i < p; i++) { varr[i] = S[i][i]; std[i] = Math.sqrt(Math.max(varr[i], 0)); }

  let somaR = 0;
  for (let i = 0; i < p; i++)
    for (let j = 0; j < p; j++) {
      const d = std[i] * std[j];
      somaR += d > 0 ? S[i][j] / d : 0;
    }
  const rBarra = p > 1 ? (somaR - p) / (p * (p - 1)) : 0;

  const F = Array.from({ length: p }, () => new Float64Array(p));
  for (let i = 0; i < p; i++)
    for (let j = 0; j < p; j++) F[i][j] = i === j ? varr[i] : rBarra * std[i] * std[j];

  // intensidade do encolhimento
  let phi = 0;
  const y = Xc.map(l => l.map(v => v * v));
  for (let i = 0; i < p; i++)
    for (let j = 0; j < p; j++) {
      let acc = 0;
      for (let k = 0; k < n; k++) acc += y[k][i] * y[k][j];
      phi += acc / n - S[i][j] * S[i][j];
    }
  let gamma = 0;
  for (let i = 0; i < p; i++)
    for (let j = 0; j < p; j++) { const d = F[i][j] - S[i][j]; gamma += d * d; }
  const delta = gamma <= 0 ? 0 : Math.min(Math.max(phi / (n * gamma), 0), 1);

  return S.map((linha, i) =>
    Array.from(linha, (v, j) => (delta * F[i][j] + (1 - delta) * v) * DIAS_ANO));
}

/** Retorno esperado por média exponencial — dá mais peso ao passado recente. */
function muEwma(X, lam = 0.97) {
  const n = X.length, p = X[0].length;
  const w = new Float64Array(n);
  let soma = 0;
  for (let i = 0; i < n; i++) { w[i] = Math.pow(lam, n - 1 - i); soma += w[i]; }
  const mu = new Float64Array(p);
  for (let i = 0; i < n; i++)
    for (let j = 0; j < p; j++) mu[j] += X[i][j] * (w[i] / soma);
  for (let j = 0; j < p; j++) mu[j] *= DIAS_ANO;
  return mu;
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

/** Duas séries no tempo, com legenda e cursor. Nunca dois eixos y — as duas
 *  séries estão na mesma unidade (retorno acumulado em %). */
function linhas(svg, datas, series, opts = {}) {
  svg.textContent = '';
  const m = { t: 14, r: 16, b: 44, l: 62 };
  const w = svg.clientWidth || svg.parentNode.clientWidth || 620;
  const h = opts.altura || 400;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('height', h);
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const todos = series.flatMap(s2 => s2.v).filter(v => isFinite(v));
  if (!todos.length) return;

  let y0 = Math.min(...todos), y1 = Math.max(...todos);
  const folga = (y1 - y0) * 0.08 || 1;
  y0 -= folga; y1 += folga;
  const X = (i) => m.l + (i / Math.max(datas.length - 1, 1)) * iw;
  const Y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

  for (let k = 0; k <= 4; k++) {
    const gy = m.t + (ih * k) / 4, val = y1 - ((y1 - y0) * k) / 4;
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: gy, y2: gy,
                                 class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: m.l - 9, y: gy + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = nf(0).format(val) + '%'; svg.appendChild(t);
  }
  if (Math.abs(y0) < Math.abs(y1) && y0 < 0) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: Y(0), y2: Y(0),
                                 stroke: css('--line-strong'), 'stroke-width': 1 }));
  }
  const passos = Math.min(6, datas.length);
  for (let k = 0; k < passos; k++) {
    const i = Math.round((k / (passos - 1)) * (datas.length - 1));
    const t = mk('text', { x: X(i), y: h - m.b + 18, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = (datas[i] || '').slice(0, 7); svg.appendChild(t);
  }

  series.forEach(s2 => {
    const pts = s2.v.map((v, i) => `${X(i)},${Y(v)}`).join('L');
    svg.appendChild(mk('path', { d: 'M' + pts, fill: 'none', stroke: s2.cor,
                                 'stroke-width': 2, 'stroke-linejoin': 'round' }));
  });

  // cursor com os valores de todas as séries na data
  const cursor = mk('line', { y1: m.t, y2: m.t + ih, class: 'gridline',
                              'stroke-width': 1, opacity: 0 });
  svg.appendChild(cursor);
  const alvo = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  alvo.addEventListener('mousemove', (ev) => {
    const cx = ev.offsetX * (w / (svg.clientWidth || w));
    const i = Math.max(0, Math.min(datas.length - 1,
      Math.round(((cx - m.l) / iw) * (datas.length - 1))));
    cursor.setAttribute('x1', X(i)); cursor.setAttribute('x2', X(i));
    cursor.setAttribute('opacity', 1);
    mostrarTip(ev, `<b>${datas[i]}</b>` + series.map(s2 =>
      `<div class="r"><span>${s2.nome}</span><span>${nf(1).format(s2.v[i])}%</span></div>`).join(''));
  });
  alvo.addEventListener('mouseleave', () => { cursor.setAttribute('opacity', 0); esconderTip(); });
  svg.appendChild(alvo);
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
// Backtest point-in-time
// ===========================================================================

/** Refaz o backtest inteiro no navegador com os parâmetros atuais.
 *
 *  O que torna isto honesto: `H.rebalances` já traz o ranking reconstruído com
 *  as demonstrações que estavam publicadas naquela data — em 02/01/2022 o
 *  balanço de 31/12/2021 ainda não existia, e não entra. O navegador só aplica
 *  os SEUS cortes (nº de ações, cota de financeiras) sobre essa lista e roda
 *  o Markowitz com a janela de retornos anterior à compra.
 */
function rodarBacktest(H, cfg) {
  const esc = H.meta.escalaRetornos || 100000;
  const nD = H.pregoes.length;
  const iDe = new Map(H.pregoes.map((d, i) => [d, i]));
  const idxData = (s) => {                       // primeiro pregão >= s
    if (iDe.has(s)) return iDe.get(s);
    let lo = 0, hi = nD;
    while (lo < hi) { const m = (lo + hi) >> 1; if (H.pregoes[m] < s) lo = m + 1; else hi = m; }
    return lo;
  };
  const serie = (t) => H.retornos[t];
  const janela = cfg.janela || H.meta.janelaRetornos || 252;
  const custo = (cfg.custoBps ?? H.meta.custoBps ?? 15) / 10000;

  const rp = new Array(nD).fill(null);
  const composicoes = [];
  const registro = [];

  for (let r = 0; r < H.rebalances.length; r++) {
    const reb = H.rebalances[r];
    const ini = idxData(reb.data);
    const fim = r + 1 < H.rebalances.length
      ? idxData(H.rebalances[r + 1].data) : nD;
    if (fim - ini < 5 || ini < 30) continue;

    const j0 = Math.max(0, ini - janela);
    const fin = reb.acoes.filter(a => a.f);
    const uti = reb.acoes.filter(a => a.u);
    const op = reb.acoes.filter(a => !a.f && !a.u);
    const vf = Math.max(0, Math.min(cfg.vagasFin, cfg.n));
    const vu = Math.max(0, Math.min(cfg.vagasUti || 0, cfg.n - vf));
    const escolhidas = [...op.slice(0, cfg.n - vf - vu), ...fin.slice(0, vf),
                        ...uti.slice(0, vu)];

    // só entram papéis com série suficiente na janela anterior à compra
    const nomes = [], colunas = [];
    for (const a of escolhidas) {
      const s = serie(a.t);
      if (!s) continue;
      let vistos = 0;
      for (let i = j0; i < ini; i++) if (s[i] !== null && s[i] !== undefined) vistos++;
      if (vistos < Math.min(120, (ini - j0) * 0.8)) continue;
      nomes.push(a.t); colunas.push(s);
    }
    if (nomes.length < 3) { registro.push(`${reb.data}: menos de 3 papéis com histórico`); continue; }

    const X = [];
    for (let i = j0; i < ini; i++)
      X.push(colunas.map(s => (s[i] ?? 0) / esc));

    const S = covLedoitWolf(X), mu = muEwma(X);
    // fronteira reduzida: o backtest roda a cada mudança de controle
    const fr = fronteira(S, mu, cfg.cap, 20, 16, 300);
    const k = Math.min(cfg.perfil, fr.length - 1);
    let w = Array.from(fr[k].w);
    const somaW = w.reduce((a, b) => a + b, 0) || 1;
    w = w.map(v => (v / somaW >= 0.005 ? v / somaW : 0));
    const s2 = w.reduce((a, b) => a + b, 0) || 1;
    w = w.map(v => v / s2);

    // buy-and-hold: os pesos derivam com o preço, como na vida real
    const valor = w.slice();
    let total = 1;
    for (let i = ini; i < fim; i++) {
      let novo = 0;
      for (let c = 0; c < nomes.length; c++) {
        const x = (colunas[c][i] ?? 0) / esc;
        valor[c] *= (1 + x);
        novo += valor[c];
      }
      let ret = novo / total - 1;
      if (i === ini) ret = (1 + ret) * (1 - custo) - 1;          // compra
      if (i === fim - 1) ret = (1 + ret) * (1 - custo) - 1;      // venda
      rp[i] = ret;
      total = novo;
    }
    composicoes.push({
      data: reb.data,
      pesos: nomes.map((t, c) => ({ t, w: w[c], f: escolhidas.find(a => a.t === t)?.f === 1 }))
                  .filter(x => x.w > 0).sort((a, b) => b.w - a.w),
    });
    registro.push(`${reb.data}: ${w.filter(v => v > 0).length} ativos`);
  }

  // recorta o período efetivamente investido
  const vivos = rp.map((v, i) => (v === null ? -1 : i)).filter(i => i >= 0);
  if (!vivos.length) return null;
  const a = vivos[0], b = vivos[vivos.length - 1];
  const datas = H.pregoes.slice(a, b + 1);
  const carteira = rp.slice(a, b + 1).map(v => v ?? 0);
  const bench = (H.benchmark || []).slice(a, b + 1).map(v => (v ?? 0) / esc);

  return { datas, carteira, bench, composicoes, registro,
           metricas: metricas(carteira, bench, H.meta.taxaLivreRisco ?? 0) };
}

const acumular = (r) => { let v = 1; return r.map(x => (v *= 1 + x) - 1); };

function metricas(rp, rb, rf) {
  const n = rp.length;
  if (!n) return {};
  const total = rp.reduce((a, x) => a * (1 + x), 1) - 1;
  const anos = n / DIAS_ANO;
  const anual = Math.pow(1 + total, 1 / anos) - 1;
  const media = rp.reduce((a, b) => a + b, 0) / n;
  const vari = rp.reduce((a, x) => a + (x - media) ** 2, 0) / (n - 1);
  const vol = Math.sqrt(vari * DIAS_ANO);

  let pico = 1, curva = 1, mdd = 0;
  for (const x of rp) { curva *= 1 + x; pico = Math.max(pico, curva); mdd = Math.min(mdd, curva / pico - 1); }

  const mb = rb.reduce((a, b) => a + b, 0) / n;
  let cov = 0, varb = 0;
  for (let i = 0; i < n; i++) { cov += (rp[i] - media) * (rb[i] - mb); varb += (rb[i] - mb) ** 2; }
  const beta = varb > 0 ? cov / varb : NaN;
  const totalB = rb.reduce((a, x) => a * (1 + x), 1) - 1;
  const anualB = Math.pow(1 + totalB, 1 / anos) - 1;
  const alfa = anual - (rf + beta * (anualB - rf));

  const ativo = rp.map((x, i) => x - rb[i]);
  const ma = ativo.reduce((a, b) => a + b, 0) / n;
  const te = Math.sqrt(ativo.reduce((a, x) => a + (x - ma) ** 2, 0) / (n - 1) * DIAS_ANO);

  return { total, anual, vol, sharpe: vol > 0 ? (anual - rf) / vol : NaN,
           mdd, beta, alfa, te, ir: te > 0 ? (ma * DIAS_ANO) / te : NaN,
           totalB, anualB, dias: n };
}

// ===========================================================================
// Estado e renderização
// ===========================================================================
let D = null;                      // dados.json
let idx = new Map();               // ticker -> empresa
let estado = { n: 30, cap: 0.15, perfil: 0, capital: 100000, unico: true,
               vagasFin: 0, vagasUti: 0 };

/** Rótulo das métricas: numa financeira as colunas medem outra coisa. */
const rotulos = (tipo) => tipo === 'financeira'
  ? { q: 'ROE', p: 'Lucro / Preço' }
  : { q: 'ROIC', p: 'EBIT / EV' };
const ehFin = (e) => (e.tipo || 'operacional') === 'financeira';
const ehUti = (e) => (e.tipo || 'operacional') === 'utilidade';
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

/** Seleciona respeitando a cota: operacionais e financeiras são ordenadas
 *  entre si, porque ROIC e ROE não estão na mesma escala. ROE é inflado por
 *  alavancagem — exatamente o que Greenblatt evitou ao escolher EBIT sobre
 *  capital —, então um ranking único favoreceria sistematicamente um lado. */
function selecionar(lista, n, vagasFin, vagasUti) {
  const fin = lista.filter(ehFin);
  const uti = lista.filter(ehUti);
  const op = lista.filter(e => !ehFin(e) && !ehUti(e));
  const vf = Math.max(0, Math.min(vagasFin, n));
  const vu = Math.max(0, Math.min(vagasUti, n - vf));
  const vo = Math.max(0, n - vf - vu);
  return { escolhidas: [...op.slice(0, vo), ...fin.slice(0, vf), ...uti.slice(0, vu)],
           op, fin, uti, vagasOp: vo, vagasFin: vf, vagasUti: vu };
}

function calcular() {
  const { escolhidas } = selecionar(elegiveis(), estado.n, estado.vagasFin,
                                  estado.vagasUti);
  const sel = escolhidas;
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
    ['Ações na carteira', String(r.pesos.length), (() => {
      const p = [];
      if (estado.vagasFin) p.push(`${estado.vagasFin} p/ financeiras`);
      if (estado.vagasUti) p.push(`${estado.vagasUti} p/ concessionárias`);
      return p.length ? p.join(' · ') : `de ${estado.n} no ranking`;
    })()],
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
  })).filter(p => { const e = idx.get(p.tk || '') || {};
                    return !ehFin(e) && !ehUti(e); }),
     { fx: v => pct(v, 0), fy: v => pct(v, 0), rotuloX: 'Earnings Yield (preço)',
       rotuloY: 'ROIC (qualidade)', altura: 400 });

  const grupos = selecionar(lista, lista.length, estado.vagasFin, estado.vagasUti);
  const posDe = new Map();
  grupos.op.forEach((e, i) => posDe.set(e.ticker, i + 1));
  grupos.fin.forEach((e, i) => posDe.set(e.ticker, i + 1));
  grupos.uti.forEach((e, i) => posDe.set(e.ticker, i + 1));
  const ordenada = [...grupos.op, ...grupos.fin, ...grupos.uti];

  el('tbRank').querySelector('tbody').innerHTML = ordenada.slice(0, 120).map((e) => {
    const dentro = r.carteira.has(e.ticker);
    const rot = rotulos(e.tipo);
    return `<tr${dentro ? ' style="background:color-mix(in srgb, var(--s1) 7%, transparent)"' : ''}>
      <td class="l num muted">${posDe.get(e.ticker)}${ehFin(e) ? ' <span class="tag">fin</span>' : ''}</td>
      <td class="l tk" title="${rot.q} / ${rot.p}">${e.ticker}</td>
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

  if (!el('p-backtest').classList.contains('hidden')) setTimeout(renderBacktest, 10);

  const ctlR = el('ctlR');
  ctlR.max = String(Math.max(frontAtual.length - 1, 0));
  el('lblR').textContent = estado.perfil === 0 ? 'mínimo'
    : `${estado.perfil + 1} de ${frontAtual.length}`;
}

let H = null, btCache = null, btChave = '';

function renderBacktest() {
  const box = el('p-backtest');
  if (!H) {
    el('btSemDados').classList.remove('hidden');
    el('btConteudo').classList.add('hidden');
    return;
  }
  el('btSemDados').classList.add('hidden');
  el('btConteudo').classList.remove('hidden');

  const cfg = { n: estado.n, cap: estado.cap, vagasFin: estado.vagasFin,
                vagasUti: estado.vagasUti,
                perfil: estado.perfil, janela: H.meta.janelaRetornos,
                custoBps: H.meta.custoBps };
  const chave = JSON.stringify(cfg);
  if (chave !== btChave) {
    // pinta o aviso e só então bloqueia: sem isso a tela congela sem explicação
    el('btStatus').textContent = 'Recalculando…';
    requestAnimationFrame(() => requestAnimationFrame(() => {
      btCache = rodarBacktest(H, cfg);
      btChave = chave;
      desenharBacktest(btCache);
    }));
    return;
  }
  desenharBacktest(btCache);
}

function desenharBacktest(r) {
  if (!r) { el('btStatus').textContent = 'Não foi possível montar carteira em nenhuma data.'; return; }
  el('btStatus').textContent = '';

  linhas(el('chBt'), r.datas, [
    { nome: 'Carteira', cor: css('--s1'), v: acumular(r.carteira).map(v => v * 100) },
    { nome: 'Ibovespa', cor: css('--s2'), v: acumular(r.bench).map(v => v * 100) },
  ], { altura: 420 });

  const m = r.metricas;
  const linhasTab = [
    ['Retorno total', pct(m.total), pct(m.totalB)],
    ['Retorno anualizado', pct(m.anual), pct(m.anualB)],
    ['Volatilidade anual', pct(m.vol), '—'],
    ['Índice de Sharpe', num(m.sharpe), '—'],
    ['Drawdown máximo', pct(m.mdd), '—'],
    ['Beta', num(m.beta), '1,00'],
    ['Alfa anual', pct(m.alfa), '—'],
    ['Tracking error', pct(m.te), '—'],
    ['Information ratio', num(m.ir), '—'],
    ['Pregões', nf(0).format(m.dias), ''],
  ];
  el('tbBt').querySelector('tbody').innerHTML = linhasTab.map(
    ([k, a, b]) => `<tr><td class="l">${k}</td><td class="num">${a}</td>
                    <td class="num muted">${b}</td></tr>`).join('');

  el('btComp').innerHTML = r.composicoes.map(c => `
    <details><summary>${c.data} — ${c.pesos.length} ativos</summary>
      <div class="scroll"><table><tbody>${c.pesos.map(x =>
        `<tr><td class="l tk">${x.t}${x.f ? ' <span class="tag">fin</span>' : ''}</td>
         <td class="num">${pct(x.w, 1)}</td></tr>`).join('')}</tbody></table></div>
    </details>`).join('');
}

function trocarAba(nome) {
  document.querySelectorAll('.tabs button').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.p === nome)));
  ['carteira', 'ranking', 'fronteira', 'backtest', 'excluidas'].forEach(p =>
    el('p-' + p).classList.toggle('hidden', p !== nome));
  render();
  if (nome === 'backtest') setTimeout(renderBacktest, 10);
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
  bind('ctlFin', 'vagasFin', c => Math.max(0, +c.value || 0),
       () => el('lblFin').textContent = el('ctlFin').value);
  bind('ctlUti', 'vagasUti', c => Math.max(0, +c.value || 0),
       () => el('lblUti').textContent = el('ctlUti').value);
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
  // Uma linha cinza ao lado da data não é aviso suficiente para uma tela que
  // imprime ordem de compra com quantidade e valor em reais. Se os números
  // forem sorteados, isso tem que gritar no topo da página.
  const modo = String(D.meta.diagnostico?.modo || '').toUpperCase();
  const dadosSinteticos = modo.startsWith('DEMONSTRA');
  el('stampFonte').textContent = dadosSinteticos
    ? '⚠ dados sintéticos de demonstração'
    : `${D.empresas.length} empresas no universo`;
  el('dadosDemo').classList.toggle('hidden', !dadosSinteticos);

  el('tbExc').querySelector('tbody').innerHTML = (D.excluidas || []).map(e =>
    `<tr><td class="l tk">${e.ticker || '—'}</td>
      <td class="l cap" title="${e.nome || ''}">${e.nome || '—'}</td>
      <td class="l cap muted">${e.setor || '—'}</td>
      <td class="l muted">${e.motivo || '—'}</td></tr>`).join('')
    || '<tr><td colspan="4" class="l muted">Nenhuma empresa excluída.</td></tr>';

  const nFin = D.empresas.filter(ehFin).length;
  el('avisoFin').classList.toggle('hidden', nFin === 0);
  if (nFin) el('nFin').textContent = String(nFin);
  const maxN = Math.min(D.empresas.length, 60);
  el('ctlN').max = String(maxN);
  if (estado.n > maxN) { estado.n = maxN; el('ctlN').value = String(maxN); el('lblN').textContent = String(maxN); }

  try {
    const rh = await fetch('historico.json?v=' + Date.now());
    if (rh.ok) {
      H = await rh.json();
      el('btInfo').textContent =
        `${H.meta.nRebalances} rebalanceamentos entre ${H.meta.inicio} e ${H.meta.fim}`;
      // Um backtest com números inventados é pior que backtest nenhum: se
      // passar por real, vira argumento para decisão de investimento.
      const sintetico = String(H.meta.modo || '').toUpperCase().startsWith('DEMONSTRA');
      el('btDemo').classList.toggle('hidden', !sintetico);
    }
  } catch (e) { /* histórico é opcional */ }

  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  ligarControles();
  render();
}

iniciar();
