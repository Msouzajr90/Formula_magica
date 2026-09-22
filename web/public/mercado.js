/* Aba de indicadores de mercado.
 *
 * Diferente das outras duas telas, aqui o navegador não recalcula nada: não há
 * parâmetro para o usuário mexer, então o `mercado.json` já chega com as curvas
 * interpoladas e os spreads prontos. O papel deste arquivo é desenhar.
 *
 * Regra que atravessa o arquivo inteiro: `null` é buraco, não zero. Uma curva
 * que não existe num prazo — prefixado de 20 anos, TIPS de 2 anos — deixa o
 * gráfico vazio ali. Nenhuma linha é esticada até o fim do eixo.
 */
'use strict';

// ===========================================================================
// Utilidades
// ===========================================================================
const nf = (d = 1) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : nf(d).format(v);
const taxa = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : nf(d).format(v) + '%';
const pp = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : (v > 0 ? '+' : '') + nf(d).format(v) + ' p.p.';
const el = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const dataBR = (iso) => {
  if (!iso) return '—';
  const [a, m, d] = String(iso).slice(0, 10).split('-');
  return `${d}/${m}/${a}`;
};
const compacto = (v) => {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return nf(2).format(v / 1e12) + ' tri';
  if (a >= 1e9) return nf(1).format(v / 1e9) + ' bi';
  if (a >= 1e6) return nf(1).format(v / 1e6) + ' mi';
  return nf(0).format(v);
};

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

function moldura(svg, altura) {
  svg.textContent = '';
  const w = svg.clientWidth || svg.parentNode.clientWidth || 640;
  svg.setAttribute('viewBox', `0 0 ${w} ${altura}`);
  svg.setAttribute('height', altura);
  return w;
}

/** Escala "bonita": limites que caem em múltiplos legíveis do passo. */
function escala(valores, folga = 0.08) {
  const v = valores.filter(x => x != null && isFinite(x));
  if (!v.length) return { min: 0, max: 1, passo: 0.25 };
  const menor = Math.min(...v), maior = Math.max(...v);
  let min = menor, max = maior;
  if (min === max) { min -= 0.5; max += 0.5; }
  const margem = (max - min) * folga;
  min -= margem; max += margem;
  // Escolhe o passo que desperdiça menos altura, em vez de fixar o número de
  // divisões. Com quatro divisões fixas, uma série de −2 a 20 caía num passo
  // de 10 e a escala ia de −10 a 30: metade do gráfico vazia, porque
  // (max−min)/4 dava 6,4 e o degrau seguinte da régua era 10. Testando de
  // quatro a sete divisões, o passo de 5 aparece e a escala fica −5 a 25.
  let passo = null, lo = 0, hi = 1, melhor = Infinity;
  for (const divisoes of [4, 5, 6, 7]) {
    const bruto = (max - min) / divisoes;
    if (!(bruto > 0)) continue;
    const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
    const p = [1, 2, 2.5, 4, 5, 10].map(k => k * mag).find(k => k >= bruto) || mag * 10;
    const a = Math.floor(min / p) * p, b = Math.ceil(max / p) * p;
    const n = Math.round((b - a) / p);
    if (n < 3 || n > 7) continue;
    if (b - a < melhor - 1e-9) { melhor = b - a; passo = p; lo = a; hi = b; }
  }
  if (passo == null) {                       // rede de segurança
    passo = (max - min) / 4 || 1;
    lo = min; hi = max;
  }
  // Num gráfico de diferença o zero entra na escala, mas a folga não pode
  // arrastá-la para o negativo quando nenhum valor é negativo: metade do
  // gráfico ficava vazia abaixo de uma região onde não existe dado.
  if (menor >= 0 && lo < 0) lo = 0;
  if (maior <= 0 && hi > 0) hi = 0;
  return { min: lo, max: hi, passo };
}

/** Rótulos no fim de cada linha, afastados até não se sobreporem.
 *  As quatro curvas ficam a menos de um ponto percentual umas das outras; sem
 *  isto os quatro textos saem empilhados no mesmo lugar e não se lê nenhum. */
function afastar(itens, minimo = 13) {
  const ord = itens.slice().sort((a, b) => a.y - b.y);
  for (let i = 1; i < ord.length; i++) {
    if (ord[i].y - ord[i - 1].y < minimo) ord[i].y = ord[i - 1].y + minimo;
  }
  return itens;
}

// ===========================================================================
// Gráfico de linhas sobre uma grade numérica (prazo em anos)
// ===========================================================================
/**
 * series: [{ nome, valores: [n|null], cor, largura, rotulo }]
 * Desenha cada trecho contínuo separadamente: onde há null a linha corta.
 */
function linhas(svg, { grade, series, eixoY, eixoX = 'Prazo (anos)', casas = 2,
                       altura = 380, zero = false }) {
  const h = altura, w = moldura(svg, h);
  const estreito = w < 620;
  const m = { t: 16, r: estreito ? 50 : 92, b: 46, l: estreito ? 44 : 58 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const vivas = series.filter(s => s.valores.some(v => v != null && isFinite(v)));
  if (!vivas.length) {
    const t = mk('text', { x: w / 2, y: h / 2, 'text-anchor': 'middle', 'font-size': 12.5 });
    t.textContent = 'Sem dados para desenhar.'; svg.appendChild(t); return;
  }

  const todos = vivas.flatMap(s => s.valores);
  if (zero) todos.push(0);
  const e = escala(todos);
  const x0 = grade[0], x1 = grade[grade.length - 1];
  const px = (v) => m.l + ((v - x0) / (x1 - x0)) * iw;
  const py = (v) => m.t + ih - ((v - e.min) / (e.max - e.min)) * ih;

  // Grade — recessiva, atrás de tudo.
  for (let v = e.min; v <= e.max + 1e-9; v += e.passo) {
    const y = py(v);
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: y, y2: y, class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: m.l - 9, y: y + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = num(v, e.passo < 1 ? 2 : 1); svg.appendChild(t);
  }
  [1, 5, 10, 15, 20].filter(p => p >= x0 && p <= x1).forEach(p => {
    svg.appendChild(mk('line', { x1: px(p), x2: px(p), y1: m.t, y2: m.t + ih, class: 'gridline', 'stroke-width': 1 }));
    const t = mk('text', { x: px(p), y: m.t + ih + 18, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = p; svg.appendChild(t);
  });
  if (zero && e.min < 0 && e.max > 0) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(0), y2: py(0),
      stroke: css('--line-strong'), 'stroke-width': 1.2 }));
  }

  const rx = mk('text', { x: m.l + iw / 2, y: h - 8, 'text-anchor': 'middle', 'font-size': 11.5 });
  rx.textContent = eixoX; svg.appendChild(rx);
  if (eixoY) {
    const ry = mk('text', { x: 13, y: m.t + ih / 2, 'font-size': 11.5, 'text-anchor': 'middle',
      transform: `rotate(-90 13 ${m.t + ih / 2})` });
    ry.textContent = eixoY; svg.appendChild(ry);
  }

  // Linhas. A ordem é invertida para que a série 0 (hoje) fique por cima.
  vivas.slice().reverse().forEach(s => {
    let d = '', abriu = false;
    grade.forEach((p, i) => {
      const v = s.valores[i];
      if (v == null || !isFinite(v)) { abriu = false; return; }
      d += (abriu ? 'L' : 'M') + px(p).toFixed(1) + ' ' + py(v).toFixed(1) + ' ';
      abriu = true;
    });
    const p = mk('path', { d, fill: 'none', stroke: s.cor,
      'stroke-width': s.largura || 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' });
    if (s.tracejado) p.setAttribute('stroke-dasharray', '6 4');
    svg.appendChild(p);
  });

  // Rótulo direto no fim de cada linha: a identidade nunca fica só na cor.
  const marcas = [];
  vivas.forEach(s => {
    let ult = -1;
    grade.forEach((p, i) => { if (s.valores[i] != null && isFinite(s.valores[i])) ult = i; });
    if (ult < 0) return;
    marcas.push({ x: px(grade[ult]), y: py(s.valores[ult]), cor: s.cor,
                  texto: s.rotulo || s.nome });
  });
  afastar(marcas);
  marcas.forEach(t => {
    const txt = mk('text', { x: Math.min(t.x + 7, m.l + iw + 6), y: t.y + 3.5,
      'font-size': 11, fill: t.cor });
    txt.textContent = t.texto; svg.appendChild(txt);
  });

  // Camada de leitura: linha vertical e valores de todas as séries no prazo.
  const cursor = mk('line', { y1: m.t, y2: m.t + ih, stroke: css('--line-strong'),
    'stroke-width': 1, 'stroke-dasharray': '3 3', opacity: 0 });
  svg.appendChild(cursor);
  const bolas = vivas.map(s => {
    const c = mk('circle', { r: 4.5, fill: s.cor, stroke: css('--surface-1'),
      'stroke-width': 2, opacity: 0 });
    svg.appendChild(c); return c;
  });
  const area = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  svg.appendChild(area);

  area.addEventListener('mousemove', (ev) => {
    const cx = ev.clientX - svg.getBoundingClientRect().left;
    const escalaSvg = (svg.viewBox.baseVal.width || w) / svg.clientWidth;
    const prazo = x0 + ((cx * escalaSvg - m.l) / iw) * (x1 - x0);
    let i = 0, melhor = Infinity;
    grade.forEach((p, k) => { const d = Math.abs(p - prazo); if (d < melhor) { melhor = d; i = k; } });

    cursor.setAttribute('x1', px(grade[i])); cursor.setAttribute('x2', px(grade[i]));
    cursor.setAttribute('opacity', 1);
    let html = `<b>${num(grade[i], grade[i] % 1 ? 1 : 0)} ano${grade[i] > 1 ? 's' : ''}</b>`;
    vivas.forEach((s, k) => {
      const v = s.valores[i];
      if (v == null || !isFinite(v)) { bolas[k].setAttribute('opacity', 0); return; }
      bolas[k].setAttribute('cx', px(grade[i]));
      bolas[k].setAttribute('cy', py(v));
      bolas[k].setAttribute('opacity', 1);
      html += `<div class="r"><span>${esc(s.nome)}</span><span>${taxa(v, casas)}</span></div>`;
    });
    mostrarTip(ev, html);
  });
  area.addEventListener('mouseleave', () => {
    cursor.setAttribute('opacity', 0);
    bolas.forEach(b => b.setAttribute('opacity', 0));
    esconderTip();
  });
}

// ===========================================================================
// Gráfico de séries no tempo
// ===========================================================================
/**
 * datas: ['2004-12-31', ...]  (ordenadas)
 * series: [{ nome, rotulo, valores: [n|null], cor }]
 * Mesma regra das curvas: null é buraco. Uma série de spread com o valor de
 * ontem carregado para a frente parece estabilidade e é ausência de dado —
 * o prefixado brasileiro de 10 anos simplesmente não existiu em vários
 * períodos, e o gráfico tem que mostrar isso.
 */
function linhasNoTempo(svg, datas, series, { altura = 320, eixoY = '',
                       referencia = null, zero = false, casas = 2,
                       formato = null, bandas = null } = {}) {
  const vivas = series.filter(s => s.valores.some(v => v != null && isFinite(v)));
  if (!vivas.length || datas.length < 2) {
    const h = moldura(svg, 88);
    const w = svg.viewBox.baseVal.width || 640;
    const t = mk('text', { x: w / 2, y: h / 2 + 4, 'text-anchor': 'middle', 'font-size': 12.5 });
    t.textContent = datas.length === 1
      ? 'Um ponto só — a série começa a se formar agora.'
      : 'Sem série para este vértice.';
    svg.appendChild(t); return;
  }

  const h = altura, w = moldura(svg, h);
  const estreito = w < 620;
  // Com faixas, o topo ganha uma tira própria para os rótulos ALTA/QUEDA:
  // dentro da área do gráfico eles ficavam por cima das linhas.
  const temBandas = !!(bandas && bandas.length);
  const m = { t: temBandas ? 30 : 16, r: estreito ? 48 : 76, b: 40,
              l: estreito ? 44 : 54 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;

  const ts = datas.map(d => Date.parse(d));
  const todos = vivas.flatMap(s => s.valores);
  if (zero) todos.push(0);
  if (referencia != null) todos.push(referencia);
  const e = escala(todos);
  const t0 = ts[0], t1 = ts[ts.length - 1];
  const px = (x) => m.l + ((x - t0) / (t1 - t0 || 1)) * iw;
  const py = (v) => m.t + ih - ((v - e.min) / (e.max - e.min)) * ih;
  const fmt = formato || ((v) => num(v, casas));

  // Faixas de fundo (os ciclos da Selic). Vêm antes de tudo, para ficarem
  // atrás das linhas.
  //
  // Cinza, não colorido. A tentação é pintar alta de vermelho e queda de
  // verde, mas as três séries deste gráfico já usam o azul, o laranja e o
  // verde da paleta — a faixa colorida faria a mesma cor significar duas
  // coisas no mesmo desenho. Dois tons do mesmo cinza separam as faixas sem
  // disputar com as linhas, e o rótulo diz qual é qual.
  (bandas || []).forEach(b => {
    const xa = Math.max(px(Date.parse(b.de)), m.l);
    const xb = Math.min(px(Date.parse(b.ate)), m.l + iw);
    if (!(xb > xa)) return;
    svg.appendChild(mk('rect', { x: xa, y: m.t, width: xb - xa, height: ih,
      fill: css('--ink'), opacity: b.sentido === 'alta' ? 0.075 : 0.022 }));
    if (xb - xa > 46) {
      const t = mk('text', { x: (xa + xb) / 2, y: m.t - 9, 'text-anchor': 'middle',
        'font-size': 9.5, 'letter-spacing': '.07em', fill: css('--ink-3') });
      t.textContent = b.sentido === 'alta' ? 'ALTA' : 'QUEDA';
      svg.appendChild(t);
    }
  });

  for (let v = e.min; v <= e.max + 1e-9; v += e.passo) {
    const y = py(v);
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: y, y2: y, class: 'gridline', 'stroke-width': 1 }));
    const tx = mk('text', { x: m.l - 9, y: y + 4, 'text-anchor': 'end', 'font-size': 11 });
    tx.textContent = num(v, e.passo < 1 ? 2 : (e.passo < 10 ? 1 : 0)); svg.appendChild(tx);
  }
  const marcos = estreito ? 3 : 5;
  for (let k = 0; k <= marcos; k++) {
    const x = t0 + (t1 - t0) * k / marcos;
    const tx = mk('text', { x: px(x), y: m.t + ih + 18, 'text-anchor': 'middle', 'font-size': 11 });
    const d = new Date(x);
    tx.textContent = (t1 - t0) > 3 * 365 * 864e5
      ? d.getFullYear() : d.toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
    svg.appendChild(tx);
  }
  if (zero && e.min < 0 && e.max > 0) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(0), y2: py(0),
      stroke: css('--line-strong'), 'stroke-width': 1.2 }));
  }
  if (referencia != null && e.min < referencia && e.max > referencia) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(referencia), y2: py(referencia),
      stroke: css('--line-strong'), 'stroke-width': 1, 'stroke-dasharray': '4 4' }));
    const tx = mk('text', { x: m.l + 5, y: py(referencia) - 5, 'font-size': 10.5 });
    tx.textContent = 'P/VP = 1 — o preço do patrimônio contábil'; svg.appendChild(tx);
  }
  if (eixoY) {
    const ry = mk('text', { x: 13, y: m.t + ih / 2, 'font-size': 11.5, 'text-anchor': 'middle',
      transform: `rotate(-90 13 ${m.t + ih / 2})` });
    ry.textContent = eixoY; svg.appendChild(ry);
  }

  vivas.slice().reverse().forEach(s => {
    let d = '', abriu = false;
    for (let i = 0; i < datas.length; i++) {
      const v = s.valores[i];
      if (v == null || !isFinite(v)) { abriu = false; continue; }
      d += (abriu ? 'L' : 'M') + px(ts[i]).toFixed(1) + ' ' + py(v).toFixed(1) + ' ';
      abriu = true;
    }
    svg.appendChild(mk('path', { d, fill: 'none', stroke: s.cor, 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  });

  const marcas = [];
  vivas.forEach(s => {
    let ult = -1;
    for (let i = 0; i < datas.length; i++) if (s.valores[i] != null && isFinite(s.valores[i])) ult = i;
    if (ult < 0) return;
    marcas.push({ x: px(ts[ult]), y: py(s.valores[ult]), cor: s.cor,
                  texto: s.rotulo || s.nome });
  });
  afastar(marcas);
  marcas.forEach(x => {
    const txt = mk('text', { x: Math.min(x.x + 7, m.l + iw + 5), y: x.y + 3.5,
      'font-size': 11, fill: x.cor });
    txt.textContent = x.texto; svg.appendChild(txt);
  });

  const cursor = mk('line', { y1: m.t, y2: m.t + ih, stroke: css('--line-strong'),
    'stroke-width': 1, 'stroke-dasharray': '3 3', opacity: 0 });
  svg.appendChild(cursor);
  const bolas = vivas.map(s => {
    const c = mk('circle', { r: 4, fill: s.cor, stroke: css('--surface-1'),
      'stroke-width': 2, opacity: 0 });
    svg.appendChild(c); return c;
  });
  const area = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  svg.appendChild(area);
  area.addEventListener('mousemove', (ev) => {
    const cx = ev.clientX - svg.getBoundingClientRect().left;
    const fator = (svg.viewBox.baseVal.width || w) / svg.clientWidth;
    const alvo = t0 + ((cx * fator - m.l) / iw) * (t1 - t0);
    // busca binária: a série tem milhares de pontos e isto roda a cada pixel
    let lo = 0, hi = ts.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (ts[mid] < alvo) lo = mid + 1; else hi = mid; }
    if (lo > 0 && Math.abs(ts[lo - 1] - alvo) < Math.abs(ts[lo] - alvo)) lo--;

    cursor.setAttribute('x1', px(ts[lo])); cursor.setAttribute('x2', px(ts[lo]));
    cursor.setAttribute('opacity', 1);
    let html = `<b>${dataBR(datas[lo])}</b>`;
    vivas.forEach((s, k) => {
      const v = s.valores[lo];
      if (v == null || !isFinite(v)) { bolas[k].setAttribute('opacity', 0); return; }
      bolas[k].setAttribute('cx', px(ts[lo]));
      bolas[k].setAttribute('cy', py(v));
      bolas[k].setAttribute('opacity', 1);
      html += `<div class="r"><span>${esc(s.nome)}</span><span>${fmt(v)}</span></div>`;
    });
    mostrarTip(ev, html);
  });
  area.addEventListener('mouseleave', () => {
    cursor.setAttribute('opacity', 0);
    bolas.forEach(b => b.setAttribute('opacity', 0));
    esconderTip();
  });
}

// ===========================================================================
// Estatística das comparações
// ===========================================================================
/** Média e desvio-padrão dos valores que existem. */
function momentos(v) {
  const x = v.filter(a => a != null && isFinite(a));
  if (x.length < 2) return null;
  const media = x.reduce((s, a) => s + a, 0) / x.length;
  const va = x.reduce((s, a) => s + (a - media) ** 2, 0) / (x.length - 1);
  return { media, dp: Math.sqrt(va), n: x.length };
}

/**
 * Põe uma série em desvios-padrão da própria média, no período visível.
 *
 * É o que permite pôr o prêmio (em pontos percentuais) e o dólar (em reais)
 * no mesmo eixo sem inventar uma relação entre as unidades. Dois eixos
 * verticais fariam as duas linhas se cruzarem onde o desenhista escolheu;
 * em desvios-padrão elas se cruzam onde os dados se cruzam.
 *
 * O preço: some o nível. Um dólar de R$ 5,10 e um de R$ 3,20 podem virar o
 * mesmo ponto se a média do período for outra — por isso o gráfico em
 * unidades originais fica a um clique de distância.
 */
function padronizar(v) {
  const m = momentos(v);
  if (!m || m.dp === 0) return v.map(() => null);
  return v.map(a => (a == null || !isFinite(a)) ? null : (a - m.media) / m.dp);
}

/** Pearson sobre os dias em que as duas séries existem. */
function correlacao(a, b) {
  const pares = [];
  for (let i = 0; i < a.length; i++) {
    if (a[i] != null && isFinite(a[i]) && b[i] != null && isFinite(b[i])) pares.push([a[i], b[i]]);
  }
  if (pares.length < 30) return null;
  const n = pares.length;
  const ma = pares.reduce((s, p) => s + p[0], 0) / n;
  const mb = pares.reduce((s, p) => s + p[1], 0) / n;
  let cov = 0, va = 0, vb = 0;
  pares.forEach(([x, y]) => { cov += (x - ma) * (y - mb); va += (x - ma) ** 2; vb += (y - mb) ** 2; });
  if (va === 0 || vb === 0) return null;
  return { r: cov / Math.sqrt(va * vb), n };
}

/**
 * Correlação entre as VARIAÇÕES das duas séries, numa janela móvel.
 *
 * Em nível, duas séries que sobem juntas ao longo de dez anos dão
 * correlação alta mesmo sem nenhuma relação entre elas — é o problema das
 * séries com tendência. A pergunta que interessa é outra: quando o prêmio
 * se mexe, o dólar se mexe junto? Isso se mede nas variações.
 */
function correlacaoMovel(a, b, janela) {
  const da = a.map((v, i) => (i && v != null && a[i - 1] != null) ? v - a[i - 1] : null);
  const db = b.map((v, i) => (i && v != null && b[i - 1] != null) ? v - b[i - 1] : null);
  const saida = new Array(a.length).fill(null);
  for (let i = janela; i < a.length; i++) {
    const c = correlacao(da.slice(i - janela, i), db.slice(i - janela, i));
    saida[i] = c ? c.r : null;
  }
  return saida;
}

/** Último valor não nulo de uma série, com a data. */
function ultimoValido(datas, v) {
  for (let i = v.length - 1; i >= 0; i--) {
    if (v[i] != null && isFinite(v[i])) return { data: datas[i], valor: v[i], i };
  }
  return null;
}

/** Corta as séries num período a partir do fim. `anos` 0 = tudo. */
function recortar(datas, series, anos) {
  if (!anos) return { datas, series };
  const limite = Date.parse(datas[datas.length - 1]) - anos * 365.25 * 864e5;
  let i = 0;
  while (i < datas.length && Date.parse(datas[i]) < limite) i++;
  return { datas: datas.slice(i), series: series.map(s => ({ ...s, valores: s.valores.slice(i) })) };
}

// ===========================================================================
// Estado e render
// ===========================================================================
let D = null;
let H = null;                    // spread_historico.json, carregado sob demanda
// O vértice padrão aqui é 10 anos. A ressalva que valia para o gráfico
// nominal — o prefixado brasileiro raramente chega a 10 anos — não vale para
// o real: a NTN-B vai a 2060 e o TIPS de 10 anos existe desde 2003. Estes
// gráficos são todos de juro REAL, então 10 anos, que é o vértice que o
// mercado cita, tem dado do começo ao fim.
const estado = { pvpAnos: 0, spreadVertice: '10.0', spreadAnos: 0,
                 dolarModo: 'padronizado', selicAnos: 0 };
const FOTOS = ['hoje', 'semana', 'mes', 'semestre'];
const CORES_FOTO = ['--t0', '--t1', '--t2', '--t3'];
const ROTULO_CURTO = { hoje: 'hoje', semana: '1 sem', mes: '1 mês', semestre: '6 meses' };

const serie = (k) => (D.juros.series || {})[k];
const naGrade = (valores, prazo) => {
  const i = D.juros.grade.indexOf(prazo);
  return i < 0 ? null : valores[i];
};

function seriesDasFotos(campo) {
  return FOTOS.filter(k => serie(k)).map((k, i) => {
    const s = serie(k);
    const v = campo === 'spreadNominal' || campo === 'spreadReal'
      ? s[campo] : s[campo].grade;
    return { nome: `${s.rotulo} (${dataBR(s.dataBR)})`, rotulo: ROTULO_CURTO[k],
             valores: v, cor: css(CORES_FOTO[i]), largura: i === 0 ? 2.4 : 1.8 };
  });
}

function legendaFotos(destino) {
  const box = el(destino);
  if (!box) return;
  box.innerHTML = FOTOS.filter(k => serie(k)).map((k, i) =>
    `<span><i class="linha" style="background:${css(CORES_FOTO[i])}"></i>${esc(serie(k).rotulo)}
       <span class="muted">· ${dataBR(serie(k).dataBR)}</span></span>`).join('');
}

function tile(k, v, h) {
  return `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${v}</div>
          <div class="h">${h || ''}</div></div>`;
}

function renderTiles() {
  const hoje = serie('hoje'), velho = serie('semestre');
  const t = [];

  const pvp = D.pvp && D.pvp.atual;
  if (pvp && pvp.valor != null) {
    t.push(tile('P/VP do Ibovespa', num(pvp.valor, 2),
      `carteira de ${dataBR(pvp.dataCarteira)} · ${pvp.nComDado} de ${pvp.nTotal} papéis`));
  }
  if (hoje) {
    const pre10 = naGrade(hoje.pre.grade, 10);
    const b10 = naGrade(hoje.ipca.grade, 10);
    const d = (atual, antigo) => antigo == null || atual == null ? ''
      : `<span class="delta">${atual > antigo ? '▲' : '▼'} ${pp(atual - antigo)} em 6 meses</span>`;
    t.push(tile('Pré 10 anos', taxa(pre10),
      velho ? d(pre10, naGrade(velho.pre.grade, 10)) : ''));
    t.push(tile('NTN-B 10 anos', taxa(b10),
      velho ? d(b10, naGrade(velho.ipca.grade, 10)) : ''));
    t.push(tile('Spread nominal 10 anos', pp(naGrade(hoje.spreadNominal, 10), 2),
      'pré brasileiro − Treasury'));
    t.push(tile('Spread real 10 anos', pp(naGrade(hoje.spreadReal, 10), 2),
      'NTN-B − TIPS'));
  }
  el('tiles').innerHTML = t.join('');
}

function renderJuros() {
  legendaFotos('legJuros'); legendaFotos('legJuros2');
  linhas(el('chPre'), { grade: D.juros.grade, series: seriesDasFotos('pre'),
    eixoY: 'Taxa (% ao ano)' });
  linhas(el('chIpca'), { grade: D.juros.grade, series: seriesDasFotos('ipca'),
    eixoY: 'Taxa real (% ao ano, acima do IPCA)' });

  const hoje = serie('hoje');
  const fim = (c) => c.alcance ? c.alcance[1] : null;
  el('notaPre').innerHTML = hoje && fim(hoje.pre)
    ? `O título prefixado mais longo vence em ${dataBR((hoje.pre.pontos.slice(-1)[0] || {}).vencimento)} — ${num(fim(hoje.pre), 1)} anos. Depois dele a curva não existe, e o gráfico termina ali.`
    : '';
  el('notaIpca').innerHTML = hoje && fim(hoje.ipca)
    ? `A NTN-B mais longa vence em ${dataBR((hoje.ipca.pontos.slice(-1)[0] || {}).vencimento)} — ${num(fim(hoje.ipca), 1)} anos. O gráfico mostra os primeiros 20.`
    : '';

  // Tabela dos títulos: uma linha por vencimento observado hoje, com a taxa do
  // mesmo vencimento nas outras três fotos.
  const linhasTab = [];
  [['pre', 'Prefixado'], ['ipca', 'NTN-B']].forEach(([fam, nome]) => {
    const pontos = hoje ? hoje[fam].pontos : [];
    pontos.forEach(p => {
      const emOutra = (k) => {
        const s = serie(k); if (!s) return null;
        const q = s[fam].pontos.find(o => o.vencimento === p.vencimento);
        return q ? q.taxa : null;
      };
      const seis = emOutra('semestre');
      linhasTab.push(`<tr>
        <td class="l tk">${esc(nome)}${p.cupom ? ' <span class="tag" title="Título com juros semestrais: a taxa é a TIR do fluxo inteiro, não a taxa à vista do prazo">cupom</span>' : ''}</td>
        <td class="l">${dataBR(p.vencimento)}</td>
        <td class="num">${num(p.prazo, 1)}</td>
        <td class="num">${taxa(p.taxa)}</td>
        <td class="num">${taxa(emOutra('semana'))}</td>
        <td class="num">${taxa(emOutra('mes'))}</td>
        <td class="num">${taxa(seis)}</td>
        <td class="num delta">${seis == null ? '—' : (p.taxa > seis ? '▲' : '▼') + ' ' + pp(p.taxa - seis)}</td>
      </tr>`);
    });
  });
  el('tbVertices').querySelector('tbody').innerHTML =
    linhasTab.join('') || '<tr><td colspan="8" class="vazio">Sem títulos na última coleta.</td></tr>';
}

function renderSpread() {
  const hoje = serie('hoje');
  if (!hoje) return;

  // Os cartões abrem pelo juro REAL de 10 anos, que é o eixo desta aba: é o
  // prêmio limpo de inflação esperada e de câmbio. O nominal vem depois,
  // porque carrega dentro dele a inflação dos dois países.
  const faixa = [];
  const br10 = naGrade(hoje.ipca.grade, 10);
  const us10 = naGrade(hoje.tips.grade, 10);
  if (br10 != null) faixa.push(tile('Juro real Brasil, 10 anos', taxa(br10, 2), 'NTN-B'));
  if (us10 != null) faixa.push(tile('Juro real EUA, 10 anos', taxa(us10, 2), 'TIPS'));
  [[10, 'real'], [20, 'real'], [10, 'nominal']].forEach(([p, tipo]) => {
    const v = naGrade(tipo === 'nominal' ? hoje.spreadNominal : hoje.spreadReal, p);
    if (v == null) return;
    faixa.push(tile(`Prêmio ${tipo === 'nominal' ? 'nominal' : 'real'} ${p} anos`, pp(v, 2),
      tipo === 'nominal' ? 'pré − Treasury' : 'NTN-B − TIPS'));
  });
  el('faixaSpread').innerHTML = faixa.join('');
  el('faixaSpread').dataset.base = faixa.length;

  linhas(el('chSpread'), {
    grade: D.juros.grade, zero: true, eixoY: 'Diferença (pontos percentuais)',
    series: [
      { nome: 'Nominal (pré − Treasury)', rotulo: 'nominal',
        valores: hoje.spreadNominal, cor: css('--s1'), largura: 2.4 },
      { nome: 'Real (NTN-B − TIPS)', rotulo: 'real',
        valores: hoje.spreadReal, cor: css('--s2'), largura: 2.4 },
    ],
  });

  // Quatro linhas, duas dimensões: a natureza da taxa (nominal ou real) é a
  // cor, o país é o traço — cheio para o Brasil, tracejado para os Estados
  // Unidos. Quatro cores separadas encobririam que "pré e Treasury" são a
  // mesma coisa em dois lugares, que é justamente o que o gráfico compara.
  // Onde cada linha começa e acaba é uma informação, não um detalhe: dizer em
  // palavras evita que o espaço vazio à direita pareça um erro do gráfico.
  const fimNom = hoje.pre.alcance ? hoje.pre.alcance[1] : null;
  const iniReal = hoje.tips.alcance ? hoje.tips.alcance[0] : null;
  el('notaSpread').innerHTML =
    `A linha nominal termina em ${num(fimNom, 1)} anos porque é ali que vence o
     título prefixado brasileiro mais longo — não existe prefixado de 20 anos.
     A real começa em ${num(iniReal, 0)} anos porque o TIPS mais curto que o
     Tesouro americano publica é o de ${num(iniReal, 0)} anos.`;

  el('legPaises').innerHTML = [
    ['Brasil — prefixado', '--s1', false],
    ['EUA — Treasury', '--s1', true],
    ['Brasil — NTN-B (real)', '--s2', false],
    ['EUA — TIPS (real)', '--s2', true],
  ].map(([n, c, tracejado]) => `<span><i class="linha" style="${tracejado
        ? `background:repeating-linear-gradient(90deg,${css(c)} 0 5px,transparent 5px 8px)`
        : `background:${css(c)}`}"></i>${esc(n)}</span>`).join('');

  linhas(el('chPaises'), {
    grade: D.juros.grade, eixoY: 'Taxa (% ao ano)',
    series: [
      { nome: 'Brasil — prefixado', rotulo: 'pré BR', valores: hoje.pre.grade,
        cor: css('--s1'), largura: 2.4 },
      { nome: 'EUA — Treasury', rotulo: 'Treasury', valores: hoje.eua.grade,
        cor: css('--s1'), largura: 2, tracejado: true },
      { nome: 'Brasil — NTN-B', rotulo: 'NTN-B', valores: hoje.ipca.grade,
        cor: css('--s2'), largura: 2.4 },
      { nome: 'EUA — TIPS', rotulo: 'TIPS', valores: hoje.tips.grade,
        cor: css('--s2'), largura: 2, tracejado: true },
    ],
  });

  const linhasTab = [];
  const bloco = (prazos, tipo, campoBR, campoEUA, nome) => {
    prazos.forEach(p => {
      const br = naGrade(hoje[campoBR].grade, p);
      const eua = naGrade(hoje[campoEUA].grade, p);
      const sp = naGrade(tipo === 'nominal' ? hoje.spreadNominal : hoje.spreadReal, p);
      const antes = (k) => {
        const s = serie(k); if (!s) return null;
        return naGrade(tipo === 'nominal' ? s.spreadNominal : s.spreadReal, p);
      };
      linhasTab.push(`<tr>
        <td class="l tk">${esc(nome)} ${p} anos</td>
        <td class="num">${taxa(br)}</td><td class="num">${taxa(eua)}</td>
        <td class="num"><b>${pp(sp, 2)}</b></td>
        <td class="num">${pp(antes('semana'), 2)}</td>
        <td class="num">${pp(antes('mes'), 2)}</td>
        <td class="num">${pp(antes('semestre'), 2)}</td>
      </tr>`);
    });
  };
  bloco(D.juros.verticesNominais || [2, 5, 10], 'nominal', 'pre', 'eua', 'Nominal');
  bloco(D.juros.verticesReais || [5, 10, 20], 'real', 'ipca', 'tips', 'Real');
  el('tbSpread').querySelector('tbody').innerHTML = linhasTab.join('');
}

// O arquivo do histórico tem 21 anos de pregões e pesa algumas centenas de
// KB. Carregar isso na abertura da página atrasaria a primeira aba, que não
// precisa dele — então só busca quando a aba Brasil × EUA é aberta.
let estadoHistorico = 'nao-pedido';   // nao-pedido | buscando | pronto | ausente
function carregarHistorico() {
  if (estadoHistorico !== 'nao-pedido') return;
  estadoHistorico = 'buscando';
  renderSpreadHistorico();
  fetch('spread_historico.json?' + encodeURIComponent(D.meta.geradoEm || ''))
    .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
    .then(j => { H = j; estadoHistorico = 'pronto'; renderSpreadHistorico(); })
    .catch(() => { H = null; estadoHistorico = 'ausente'; renderSpreadHistorico(); });
}

/** A curva real americana. Arquivos antigos não a traziam; ela é a
 *  brasileira menos o spread, que é a mesma conta feita do outro lado. */
function euaReal(v) {
  const direto = (H.euaReal || {})[v];
  if (direto) return direto;
  const br = (H.brasilNtnb || {})[v], sp = (H.real || {})[v];
  if (!br || !sp) return null;
  return br.map((a, i) => (a == null || sp[i] == null) ? null : +(a - sp[i]).toFixed(3));
}

const anosDoVertice = (v) => parseFloat(v);

// ---------------------------------------------------------------------------
// 1. Juro real: Brasil, Estados Unidos e a diferença
// ---------------------------------------------------------------------------
function renderReal() {
  const v = estado.spreadVertice;
  const br = (H.brasilNtnb || {})[v] || null;
  const us = euaReal(v);
  const sp = (H.real || {})[v] || null;
  const n = anosDoVertice(v);

  const series = [];
  if (br) series.push({ nome: `Brasil — NTN-B ${n} anos`, rotulo: 'Brasil',
    valores: br, cor: css('--s1') });
  if (us) series.push({ nome: `Estados Unidos — TIPS ${n} anos`, rotulo: 'EUA',
    valores: us, cor: css('--s2') });
  if (sp) series.push({ nome: 'Diferença (Brasil − EUA)', rotulo: 'diferença',
    valores: sp, cor: css('--s3') });

  const r = recortar(H.datas, series, estado.spreadAnos);
  linhasNoTempo(el('chReal'), r.datas, r.series, {
    altura: 360, zero: true, eixoY: 'Juro real (% a.a.) e diferença (p.p.)',
    formato: (x) => num(x, 2),
  });

  const uBr = br && ultimoValido(H.datas, br);
  const uUs = us && ultimoValido(H.datas, us);
  const uSp = sp && ultimoValido(H.datas, sp);
  const mSp = sp && momentos(sp);
  const extremos = sp ? (() => {
    let lo = null, hi = null;
    sp.forEach((x, i) => {
      if (x == null) return;
      if (!lo || x < lo.valor) lo = { valor: x, data: H.datas[i] };
      if (!hi || x > hi.valor) hi = { valor: x, data: H.datas[i] };
    });
    return { lo, hi };
  })() : null;

  el('notaReal').innerHTML = !uSp ? 'Sem série neste prazo.' : `
    Hoje, em ${n} anos: o Brasil paga <b>${taxa(uBr.valor, 2)}</b> de juro real e os
    Estados Unidos, <b>${taxa(uUs.valor, 2)}</b> — uma diferença de
    <b>${pp(uSp.valor, 2)}</b>.
    A média do período inteiro é ${pp(mSp.media, 2)}, com desvio-padrão de
    ${num(mSp.dp, 2)} p.p.; hoje estamos
    <b>${num((uSp.valor - mSp.media) / mSp.dp, 1)} desvio(s)-padrão</b> da média.
    O mínimo foi ${pp(extremos.lo.valor, 2)} em ${dataBR(extremos.lo.data)} e o máximo
    ${pp(extremos.hi.valor, 2)} em ${dataBR(extremos.hi.data)}.`;
}

// ---------------------------------------------------------------------------
// 2. O prêmio e o dólar
// ---------------------------------------------------------------------------
function renderDolar() {
  const caixa = el('cardDolar');
  const dol = H.dolar || null;
  if (!dol) {
    caixa.classList.add('hidden');
    return;
  }
  caixa.classList.remove('hidden');

  const v = estado.spreadVertice;
  const sp = (H.real || {})[v] || null;
  const n = anosDoVertice(v);
  if (!sp) { el('chDolar').textContent = ''; return; }

  const juntos = estado.dolarModo === 'padronizado';
  el('chDolar').classList.toggle('hidden', !juntos);
  el('chDolarA').classList.toggle('hidden', juntos);
  el('chDolarB').classList.toggle('hidden', juntos);

  const r = recortar(H.datas, [
    { nome: `Prêmio real ${n} anos`, rotulo: 'prêmio', valores: sp, cor: css('--s3') },
    { nome: 'Dólar (PTAX venda)', rotulo: 'dólar', valores: dol, cor: css('--s2') },
  ], estado.spreadAnos);
  const [sSp, sDol] = r.series;

  if (juntos) {
    // Padronizadas DENTRO do período visível: trocar o período reescala as
    // duas, o que é a leitura certa — "como isto se moveu, para o que é
    // normal neste período".
    linhasNoTempo(el('chDolar'), r.datas, [
      { ...sSp, valores: padronizar(sSp.valores) },
      { ...sDol, valores: padronizar(sDol.valores) },
    ], { altura: 320, zero: true, eixoY: 'Desvios-padrão da média do período',
         formato: (x) => num(x, 2) + ' dp' });
  } else {
    linhasNoTempo(el('chDolarA'), r.datas, [sSp], {
      altura: 210, zero: true, eixoY: 'Prêmio real (p.p.)', formato: (x) => pp(x, 2) });
    linhasNoTempo(el('chDolarB'), r.datas, [sDol], {
      altura: 210, eixoY: 'R$ por US$', formato: (x) => 'R$ ' + num(x, 4) });
  }

  // Correlação móvel das VARIAÇÕES, janela de um ano de pregões.
  const movel = correlacaoMovel(sSp.valores, sDol.valores, 252);
  linhasNoTempo(el('chCorrel'), r.datas, [
    { nome: 'Correlação das variações diárias (janela de 1 ano)',
      rotulo: 'correlação', valores: movel, cor: css('--s1') },
  ], { altura: 190, zero: true, eixoY: 'Correlação', formato: (x) => num(x, 2) });

  const nivel = correlacao(sSp.valores, sDol.valores);
  const varia = correlacao(
    sSp.valores.map((x, i) => (i && x != null && sSp.valores[i - 1] != null) ? x - sSp.valores[i - 1] : null),
    sDol.valores.map((x, i) => (i && x != null && sDol.valores[i - 1] != null) ? x - sDol.valores[i - 1] : null));
  const vivos = movel.filter(x => x != null);
  const positivas = vivos.filter(x => x > 0).length;

  el('notaDolar').innerHTML = `
    No período escolhido, prêmio e dólar andam juntos em <b>nível</b> com
    correlação de <b>${num(nivel ? nivel.r : null, 2)}</b> — mas isso diz pouco:
    duas séries com tendência no mesmo sentido dão correlação alta sem nenhuma
    relação entre elas.
    Nas <b>variações diárias</b>, que é a pergunta de verdade, a correlação cai
    para <b>${num(varia ? varia.r : null, 2)}</b>.
    Na janela móvel de um ano, ela é positiva em
    <b>${vivos.length ? num(100 * positivas / vivos.length, 0) : '—'}%</b> do tempo e
    ${vivos.length ? `varia de ${num(Math.min(...vivos), 2)} a ${num(Math.max(...vivos), 2)}` : '—'}:
    a relação existe, muda de força e chega a mudar de sinal.`;
}

// ---------------------------------------------------------------------------
// 3. Juro real e o ciclo da Selic
// ---------------------------------------------------------------------------
function renderSelic() {
  const caixa = el('cardSelic');
  const meta = H.selicMeta || null;
  if (!meta) { caixa.classList.add('hidden'); return; }
  caixa.classList.remove('hidden');

  const exAnte = H.juroRealExAnte || null;
  const longo = (H.brasilNtnb || {})['10.0'] || null;

  const series = [
    { nome: 'Meta Selic (nominal)', rotulo: 'Selic', valores: meta, cor: css('--s1') },
  ];
  if (exAnte) series.push({ nome: 'Juro real ex-ante, 1 ano', rotulo: 'real 1a',
    valores: exAnte, cor: css('--s2') });
  if (longo) series.push({ nome: 'Juro real longo — NTN-B 10 anos', rotulo: 'real 10a',
    valores: longo, cor: css('--s3') });

  const r = recortar(H.datas, series, estado.selicAnos);
  const limite = Date.parse(r.datas[0]);
  const bandas = (H.ciclosSelic || []).filter(c => Date.parse(c.ate) >= limite);
  linhasNoTempo(el('chSelic'), r.datas, r.series, {
    altura: 380, zero: true, eixoY: '% ao ano', bandas,
    formato: (x) => taxa(x, 2),
  });

  // A tabela responde a pergunta que o gráfico só insinua: em cada ciclo, o
  // juro real longo acompanhou a Selic ou foi para o outro lado?
  const emData = (d) => {
    let lo = 0, hi = H.datas.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (H.datas[m] < d) lo = m + 1; else hi = m; }
    return lo;
  };
  const valorEm = (s, i) => {
    if (!s) return null;
    for (let k = i; k >= 0 && k > i - 15; k--) if (s[k] != null) return s[k];
    return null;
  };
  const linhasTab = (H.ciclosSelic || []).slice().reverse().map(c => {
    const ia = emData(c.de), ib = emData(c.ate);
    const la = valorEm(longo, ia), lb = valorEm(longo, ib);
    const ea = valorEm(exAnte, ia), eb = valorEm(exAnte, ib);
    const dl = (la != null && lb != null) ? lb - la : null;
    const de = (ea != null && eb != null) ? eb - ea : null;
    const junto = (dl == null) ? '—'
      : (Math.sign(dl) === Math.sign(c.fim - c.inicio) ? 'acompanhou' : 'foi ao contrário');
    return `<tr>
      <td class="l"><span class="tag">${c.sentido}</span></td>
      <td class="l muted">${dataBR(c.de)} → ${dataBR(c.ate)}</td>
      <td class="num">${num(c.inicio, 2)} → ${num(c.fim, 2)}</td>
      <td class="num">${pp(c.fim - c.inicio, 2)}</td>
      <td class="num">${pp(de, 2)}</td>
      <td class="num">${pp(dl, 2)}</td>
      <td class="l muted">${junto}</td>
    </tr>`;
  });
  el('tbCiclos').querySelector('tbody').innerHTML = linhasTab.join('')
    || '<tr><td colspan="7" class="vazio">Sem ciclos no arquivo.</td></tr>';

  const uM = ultimoValido(H.datas, meta);
  const uE = exAnte && ultimoValido(H.datas, exAnte);
  const uL = longo && ultimoValido(H.datas, longo);
  const foco = H.focusIpca12m && ultimoValido(H.datas, H.focusIpca12m);
  const atual = (H.ciclosSelic || [])[(H.ciclosSelic || []).length - 1];
  el('notaSelic').innerHTML = `
    Hoje a meta Selic está em <b>${taxa(uM.valor, 2)}</b>.
    ${foco ? `Com o Focus esperando <b>${taxa(foco.valor, 2)}</b> de IPCA para os
      próximos doze meses, o juro real ex-ante de um ano é
      <b>${taxa(uE ? uE.valor : null, 2)}</b>` : ''}${uL ? `, e o juro real longo,
      pela NTN-B de 10 anos, está em <b>${taxa(uL.valor, 2)}</b>` : ''}.
    ${atual ? `O ciclo em curso é de <b>${atual.sentido}</b>, aberto em
      ${dataBR(atual.de)}, e já moveu a meta ${pp(atual.fim - atual.inicio, 2)}.` : ''}
    Nos ${(H.ciclosSelic || []).length} ciclos desde 2004, a ponta curta obedece ao
    Copom por construção; a ponta longa é que revela se o mercado comprou a
    história — a última coluna da tabela diz em quais ela acompanhou.`;
}

function renderSpreadHistorico() {
  const caixa = el('histSpread');
  if (!caixa) return;
  if (!H) {
    ['chReal', 'chDolar', 'chDolarA', 'chDolarB', 'chCorrel', 'chSelic']
      .forEach(id => { const e = el(id); if (e) e.textContent = ''; });
    el('histStatus').textContent = {
      'nao-pedido': '',
      'buscando': 'Carregando 21 anos de pregões…',
      'ausente': 'O arquivo spread_historico.json ainda não existe. Ele é gerado '
               + 'junto com o mercado.json — rode a ação Atualizar mercado no GitHub.',
    }[estadoHistorico] || '';
    return;
  }

  if (H.demo && !el('avisoHistDemo')) {
    caixa.insertAdjacentHTML('afterbegin',
      '<div class="warn" id="avisoHistDemo"><b>Curvas inventadas.</b> Este '
      + '<code>spread_historico.json</code> é o fixture de tela — a Selic, o '
      + 'dólar e o Focus são reais, mas NTN-B, TIPS e prefixado são passeios '
      + 'aleatórios. Rode <code>atualizar_mercado.py</code> para trocar pelo '
      + 'arquivo de verdade.</div>');
  }

  renderReal();
  renderDolar();
  renderSelic();

  // Os três cartões que dependem do arquivo histórico entram quando ele
  // chega; os outros já estão na tela desde a abertura da aba.
  const caixaTiles = el('faixaSpread');
  const base = +(caixaTiles.dataset.base || 0);
  if (base && caixaTiles.children.length <= base) {
    const extra = [];
    const uD = H.dolar && ultimoValido(H.datas, H.dolar);
    const uS = H.selicMeta && ultimoValido(H.datas, H.selicMeta);
    const uE = H.juroRealExAnte && ultimoValido(H.datas, H.juroRealExAnte);
    if (uD) extra.push(tile('Dólar', 'R$ ' + num(uD.valor, 4),
      `PTAX de ${dataBR(uD.data)}`));
    if (uS) extra.push(tile('Meta Selic', taxa(uS.valor, 2), 'definida pelo Copom'));
    if (uE) extra.push(tile('Juro real ex-ante, 1 ano', taxa(uE.valor, 2),
      'pré 1 ano descontado do Focus'));
    caixaTiles.insertAdjacentHTML('beforeend', extra.join(''));
  }

  const partes = [`${H.datas.length} pregões, de ${dataBR(H.datas[0])} a `
                  + `${dataBR(H.datas[H.datas.length - 1])}`];
  const sp = (H.real || {})[estado.spreadVertice];
  if (sp) {
    const faltam = sp.filter(x => x == null).length;
    if (faltam) partes.push(`${faltam} dias sem o par completo neste prazo`);
  }
  if (!H.dolar) partes.push('sem dólar no arquivo — rode a coleta de novo');
  if (!H.selicMeta) partes.push('sem Selic no arquivo — rode a coleta de novo');
  el('histStatus').textContent = partes.join(' · ');
}

function renderPvp() {
  const bloco = D.pvp || {};
  const atual = bloco.atual;
  if (!atual || atual.valor == null) {
    el('pvpSemDados').classList.remove('hidden');
    el('pvpConteudo').classList.add('hidden');
    return;
  }
  el('pvpSemDados').classList.add('hidden');
  el('pvpConteudo').classList.remove('hidden');

  const hist = (bloco.historico || []);
  const datas = hist.map(x => x[0]);
  const base = [{ nome: 'P/VP do índice', rotulo: 'P/VP',
                  valores: hist.map(x => x[1]), cor: css('--s1') }];
  const r = recortar(datas, base, estado.pvpAnos);
  linhasNoTempo(el('chPvp'), r.datas, r.series, { referencia: 1, altura: 340 });
  el('pvpStatus').textContent = hist.length > 1
    ? `${hist.length} pontos, de ${dataBR(datas[0])} a ${dataBR(datas[datas.length - 1])}`
    : 'a série começa a se formar a partir de agora';

  el('notaPvp').innerHTML =
    `Hoje: <b>${num(atual.valor, 2)}</b> — R$ ${compacto(atual.valorMercado)} de valor de
     mercado sobre R$ ${compacto(atual.patrimonio)} de patrimônio líquido.
     O cálculo cobre ${num((atual.cobertura || 0) * 100, 1)}% do peso do índice
     (${atual.nComDado} de ${atual.nTotal} papéis)${
       (atual.faltando || []).length
         ? `; ficaram de fora ${esc(atual.faltando.join(', '))}, sem patrimônio ou sem preço`
         : ''}.`;

  const emp = bloco.empresas || [];
  el('contagemPvp').innerHTML = `<b>${emp.length}</b> papéis com preço e patrimônio.`;
  el('tbPvp').querySelector('tbody').innerHTML = emp.map(e => `<tr>
      <td class="l tk">${esc(e.ticker)}</td>
      <td class="l cap" title="${esc(e.nome || '')}">${esc(e.nome || '—')}</td>
      <td class="num">${num(e.peso, 2)}%</td>
      <td class="num">${num(e.preco, 2)}</td>
      <td class="num">${num(e.vpa, 2)}</td>
      <td class="num"><b>${num(e.pvp, 2)}</b></td>
      <td class="l muted">${dataBR(e.dtBalanco)}</td>
      <td class="l muted">${esc(e.fonteAcoes || '—')}</td>
    </tr>`).join('') || '<tr><td colspan="8" class="vazio">Sem empresas.</td></tr>';
}

function render() {
  renderTiles();
  renderJuros();
  renderSpread();
  renderSpreadHistorico();
  renderPvp();
}

function trocarAba(nome) {
  document.querySelectorAll('.tabs button').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.p === nome)));
  ['juros', 'spread', 'pvp', 'metodo'].forEach(p =>
    el('p-' + p).classList.toggle('hidden', p !== nome));
  if (nome === 'spread') carregarHistorico();
  // Os gráficos das abas escondidas nascem com largura zero; redesenhar ao
  // abrir é o que evita o gráfico de 0 pixel que aparecia na primeira visita.
  render();
}

// ===========================================================================
// Carga
// ===========================================================================
async function iniciar() {
  try {
    const r = await fetch('mercado.json?' + Date.now());
    if (!r.ok) throw new Error(`mercado.json respondeu ${r.status}`);
    D = await r.json();
  } catch (e) {
    el('loading').classList.add('hidden');
    const box = el('erro');
    box.classList.remove('hidden');
    box.innerHTML = `Não consegui carregar <code>mercado.json</code>.<br>
      <span class="muted">${esc(e.message)}</span><br><br>
      O arquivo é gerado por <code>atualizar_mercado.py</code> — rode a ação
      <b>Atualizar mercado</b> no GitHub.`;
    return;
  }

  const meta = D.meta || {};
  if (meta.demo) el('dadosDemo').classList.remove('hidden');
  if ((meta.avisos || []).length) {
    el('avisos').innerHTML = meta.avisos.map(a =>
      `<div class="warn"><b>Aviso da última coleta.</b> ${esc(a)}</div>`).join('');
  }
  const hoje = (D.juros && D.juros.series && D.juros.series.hoje) || null;
  el('stamp').textContent = hoje ? dataBR(hoje.dataBR) : '—';
  el('stampGerado').textContent = meta.geradoEm ? `coletado em ${meta.geradoEm}` : '';

  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');

  document.querySelectorAll('.tabs button').forEach(b =>
    b.addEventListener('click', () => trocarAba(b.dataset.p)));

  el('ctlVertice').addEventListener('change', (e) => {
    estado.spreadVertice = e.target.value; renderSpreadHistorico();
  });
  el('ctlSpreadAnos').addEventListener('change', (e) => {
    estado.spreadAnos = +e.target.value; renderSpreadHistorico();
  });
  el('ctlDolarModo').addEventListener('change', (e) => {
    estado.dolarModo = e.target.value; renderDolar();
  });
  el('ctlSelicAnos').addEventListener('change', (e) => {
    estado.selicAnos = +e.target.value; renderSelic();
  });
  el('ctlPvpAnos').addEventListener('change', (e) => {
    estado.pvpAnos = +e.target.value; renderPvp();
  });

  let t = null;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 150); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);

  render();
}

iniciar();
