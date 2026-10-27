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
      t.textContent = b.rotulo || (b.sentido === 'alta' ? 'ALTA' : 'QUEDA');
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
    // Série curta (o histórico de crédito nasce com uma semana): com mês e
    // ano, as seis marcas saíam todas "set. de 26".
    tx.textContent = (t1 - t0) > 3 * 365 * 864e5 ? d.getFullYear()
      : (t1 - t0) > 120 * 864e5 ? d.toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' })
      // As datas ISO viram meia-noite UTC; formatadas no fuso de Brasília,
      // caíam no dia anterior (22/09 saía 21/09).
      : d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', timeZone: 'UTC' });
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
    const caminho = mk('path', { d, fill: 'none', stroke: s.cor, 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round' });
    if (s.tracejado) caminho.setAttribute('stroke-dasharray', '6 4');
    svg.appendChild(caminho);
    // Série de poucos pontos: sem marcador, um dia isolado entre lacunas não
    // desenha nada (um "M" sem "L"). O histórico de crédito nasce assim.
    if (datas.length <= 40) {
      for (let i = 0; i < datas.length; i++) {
        const v = s.valores[i];
        if (v == null || !isFinite(v)) continue;
        svg.appendChild(mk('circle', { cx: px(ts[i]), cy: py(v), r: 2.6, fill: s.cor }));
      }
    }
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
                 dolarModo: 'padronizado', selicAnos: 0,
                 creditoSerie: 'ipcaIsenta', creditoVertice: '3', creditoLimiar: 0.05,
                 papelGrupo: '', papelBusca: '', papelOrdem: 'spread',
                 pvpPapel: '', pvpPapelAnos: 0 };
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
    // Quando a foto caiu longe do alvo, o rótulo dela diz a distância de
    // verdade ("5 semanas atrás"); a etiqueta da ponta da linha acompanha.
    const curto = /semanas|dias|meses/.test(s.rotulo || '') && s.rotulo !== '6 meses atrás'
      ? s.rotulo.replace(/ atrás$/, '').replace(' semanas', ' sem') : ROTULO_CURTO[k];
    return { nome: `${s.rotulo} (${dataBR(s.dataBR)})`, rotulo: curto,
             valores: v, cor: css(CORES_FOTO[i]), largura: i === 0 ? 2.4 : 1.8 };
  });
}

function legendaFotos(destino) {
  const box = el(destino);
  if (!box) return;
  box.innerHTML = FOTOS.filter(k => serie(k)).map((k, i) =>
    `<span><i class="linha" style="background:${css(CORES_FOTO[i])}"></i>${esc(serie(k).rotulo)}
       <span class="muted">· ${dataBR(serie(k).dataBR)}${serie(k).fonteBR ? ` · ${esc(serie(k).fonteBR)}` : ''}</span></span>`).join('');
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
  // Legenda de linha que não está no gráfico é pior que legenda nenhuma:
  // quem olha procura a linha e conclui que ela está escondida atrás de outra.
  const leg = el('legExAnte');
  if (leg) leg.classList.toggle('hidden', !exAnte);

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

  // Montado por pedaços, não por template com condicional no meio: a versão
  // anterior deixava ", e o juro real longo," solto na tela quando o Focus
  // faltava. Frase que depende de série pode perder a série.
  const frase = [`Hoje a meta Selic está em <b>${taxa(uM.valor, 2)}</b>`];
  if (foco && uE) {
    frase.push(`com o Focus esperando <b>${taxa(foco.valor, 2)}</b> de IPCA para
      os próximos doze meses, o juro real ex-ante de um ano é
      <b>${taxa(uE.valor, 2)}</b>`);
  }
  if (uL) frase.push(`o juro real longo, pela NTN-B de 10 anos, está em
    <b>${taxa(uL.valor, 2)}</b>`);

  const fim = [];
  if (atual) fim.push(`O ciclo em curso é de <b>${atual.sentido}</b>, aberto em
    ${dataBR(atual.de)}, e já moveu a meta ${pp(atual.fim - atual.inicio, 2)}.`);
  fim.push(`Nos ${(H.ciclosSelic || []).length} ciclos desde 2004, a ponta curta
    obedece ao Copom por construção; a ponta longa é que revela se o mercado
    comprou a história — a última coluna da tabela diz em quais ela acompanhou.`);
  if (!H.juroRealExAnte) {
    fim.push(`<span class="muted">A linha do juro real ex-ante está faltando:
      a expectativa de inflação do Focus não veio na última coleta. O motivo
      aparece no aviso no topo da página.</span>`);
  }
  el('notaSelic').innerHTML = frase.join('; ') + '. ' + fim.join(' ');
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
  el('tbPvp').querySelector('tbody').innerHTML = emp.map(e => `<tr class="clicavel" data-tk="${esc(e.ticker)}"
        title="Ver o histórico de P/VP de ${esc(e.ticker)}">
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

// ===========================================================================
// P/VP por papel
// ===========================================================================
// Arquivo próprio (`pvp_papeis.json`), baixado só quando a aba abre: são 170
// séries semanais, e quem veio ver a curva de juros não precisa delas. O ponto
// de HOJE vem do `dados.json` (o preço do dia dividido pelo VPA guardado), que
// o robô atualiza todo dia; o histórico só ganha um ponto por semana.
let PP = null, PRECOS = null, ppPromessa = null;

function carregarPvpPapeis() {
  if (ppPromessa) return ppPromessa;
  ppPromessa = (async () => {
    try {
      const [r1, r2] = await Promise.all([
        fetch('pvp_papeis.json?' + Date.now()), fetch('dados.json?' + Date.now())]);
      if (!r1.ok) throw new Error(`pvp_papeis.json respondeu ${r1.status}`);
      PP = await r1.json();
      PRECOS = { _data: null };
      if (r2.ok) {
        const d = await r2.json();
        PRECOS._data = String((d.meta || {}).geradoEm || '').slice(0, 10) || null;
        [...(d.empresas || []), ...(d.excluidas || [])].forEach(e => {
          if (e.ticker && e.preco > 0) PRECOS[e.ticker] = e.preco;
        });
      }
    } catch (e) {
      PP = { erro: e.message };
    }
    preencherListaPapeis();
    renderPvpPapel();
  })();
  return ppPromessa;
}

function preencherListaPapeis() {
  if (!PP || !PP.papeis) return;
  const tks = Object.keys(PP.papeis).sort();
  el('listaPvpPapeis').innerHTML = tks.map(t =>
    `<option value="${esc(t)}">${esc(PP.papeis[t].nome || '')}</option>`).join('');
  if (!estado.pvpPapel) estado.pvpPapel = PP.papeis.PETR4 ? 'PETR4' : tks[0];
  el('ctlPvpPapel').value = estado.pvpPapel;
}

function escolherPapelPvp(t, rolar = false) {
  t = String(t || '').trim().toUpperCase();
  if (!t) return;
  estado.pvpPapel = t;
  el('ctlPvpPapel').value = t;
  try { history.replaceState(null, '', '#pvp=' + encodeURIComponent(t)); } catch (e) { /* sem histórico */ }
  renderPvpPapel();
  if (rolar) el('cardPvpPapel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** Quantil por interpolação linear (o "tipo 7" das planilhas). */
function quantil(ordenados, q) {
  if (!ordenados.length) return null;
  const pos = (ordenados.length - 1) * q, i = Math.floor(pos), f = pos - i;
  return ordenados[i] + (ordenados[Math.min(i + 1, ordenados.length - 1)] - ordenados[i]) * f;
}

function renderPvpPapel() {
  const svg = el('chPvpPapel'), nota = el('notaPvpPapel'), vazio = el('pvpPapelVazio');
  if (!svg) return;
  const mostrar = (msg) => {
    vazio.innerHTML = msg; vazio.classList.remove('hidden');
    el('pvpPapelConteudo').classList.add('hidden');
  };
  if (!PP) { mostrar('Carregando o histórico…'); return; }
  if (PP.erro) {
    mostrar(`O histórico por papel ainda não foi gerado. Ele nasce no seu computador,
      com <code>pvp_papeis.bat</code> (os balanços antigos vêm da CVM, que recusa o robô).
      <br><span class="muted">${esc(PP.erro)}</span>`);
    return;
  }
  const t = estado.pvpPapel, info = PP.papeis[t];
  if (!info) {
    const motivo = (PP.meta?.fora || {})[t];
    mostrar(motivo
      ? `<b>${esc(t)}</b> não tem histórico: ${esc(motivo)}.`
      : `Não encontrei <b>${esc(t)}</b>. Digite um código da lista (ex.: PETR4).`);
    return;
  }
  vazio.classList.add('hidden');
  el('pvpPapelConteudo').classList.remove('hidden');

  // Ponto de hoje: preço do dados.json ÷ VPA guardado. Só entra se for mais
  // novo que a última semana gravada — senão repetiria o mesmo dia.
  const preco = PRECOS && PRECOS[t];
  let hoje = null;
  if (preco > 0 && info.vpa > 0 && PRECOS._data && PRECOS._data > PP.datas[PP.datas.length - 1]) {
    hoje = { data: PRECOS._data, valor: preco / info.vpa, preco };
  }

  // Começa no primeiro ponto do papel, não em 2015: uma ação que abriu capital
  // em 2020 ficaria com cinco anos de eixo vazio, e "desde 2015" na nota mentiria.
  let i0 = info.s.findIndex(v => v != null && isFinite(v));
  if (i0 < 0) i0 = 0;
  const r = recortar(PP.datas.slice(i0), [{ valores: info.s.slice(i0) }], estado.pvpPapelAnos);
  const datas = r.datas, valores = r.series[0].valores;
  const vivos = valores.map((v, i) => ({ v, i })).filter(x => x.v != null && isFinite(x.v));
  const ord = vivos.map(x => x.v).sort((a, b) => a - b);
  const est = {
    mediana: quantil(ord, 0.5), p25: quantil(ord, 0.25), p75: quantil(ord, 0.75),
    min: vivos.reduce((a, b) => (b.v < a.v ? b : a), vivos[0] || { v: null }),
    max: vivos.reduce((a, b) => (b.v > a.v ? b : a), vivos[0] || { v: null }),
  };
  const ultimo = hoje || (vivos.length ? { data: datas[vivos[vivos.length - 1].i],
                                          valor: vivos[vivos.length - 1].v } : null);
  graficoPvpPapel(svg, datas, valores, est, hoje);

  el('pvpPapelTitulo').textContent = `${t} · ${info.nome || ''}`;
  if (!ultimo) { nota.textContent = ''; return; }
  const abaixo = ord.filter(v => v < ultimo.valor).length;
  const periodo = estado.pvpPapelAnos ? `nos últimos ${estado.pvpPapelAnos} anos`
                                      : `desde ${dataBR(datas[0]).slice(3)}`;
  nota.innerHTML =
    `<b>P/VP ${hoje ? 'de hoje' : `de ${dataBR(ultimo.data)}`}: ${num(ultimo.valor, 2)}</b>${
      hoje ? ` (preço de R$ ${num(hoje.preco, 2)} ÷ VPA de R$ ${num(info.vpa, 2)})` : ''}.
     ${ord.length ? `Mediana ${periodo}: <b>${num(est.mediana, 2)}</b>; metade das semanas entre
     ${num(est.p25, 2)} e ${num(est.p75, 2)}. O P/VP esteve abaixo do atual em
     <b>${Math.round(100 * abaixo / ord.length)}%</b> das semanas.
     Mínimo ${num(est.min.v, 2)} em ${dataBR(datas[est.min.i])}; máximo ${num(est.max.v, 2)}
     em ${dataBR(datas[est.max.i])}.` : ''}
     <br><span class="muted">Patrimônio dos controladores, balanço de ${dataBR(info.dtBalanco)}
     (o robô só move o preço; balanço novo entra quando o histórico é refeito).
     Nº de ações de hoje aplicado ao passado: emissões e recompras distorcem os anos
     antigos.</span>`;
}

/** Uma série semanal com a faixa entre os quartis, a mediana e o ponto de hoje. */
function graficoPvpPapel(svg, datas, valores, est, hoje) {
  const h = 340, w = moldura(svg, h);
  const estreito = w < 620;
  const m = { t: 16, r: estreito ? 64 : 96, b: 40, l: estreito ? 40 : 50 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const ts = datas.map(d => Date.parse(d));
  if (hoje) ts.push(Date.parse(hoje.data));
  const todos = valores.concat(hoje ? [hoje.valor] : []);
  const e = escala(todos);
  const t0 = ts[0], t1 = ts[ts.length - 1];
  const px = (x) => m.l + ((x - t0) / (t1 - t0 || 1)) * iw;
  const py = (v) => m.t + ih - ((v - e.min) / (e.max - e.min)) * ih;
  const azul = css('--s1');

  // Faixa dos quartis primeiro, para ficar atrás de tudo.
  if (est.p25 != null && est.p75 != null) {
    svg.appendChild(mk('rect', { x: m.l, y: py(est.p75), width: iw,
      height: Math.max(py(est.p25) - py(est.p75), 1), fill: azul, opacity: 0.09 }));
  }
  for (let v = e.min; v <= e.max + 1e-9; v += e.passo) {
    const y = py(v);
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: y, y2: y, class: 'gridline', 'stroke-width': 1 }));
    const tx = mk('text', { x: m.l - 8, y: y + 4, 'text-anchor': 'end', 'font-size': 11 });
    tx.textContent = num(v, e.passo < 1 ? (e.passo < 0.1 ? 2 : 1) : 0); svg.appendChild(tx);
  }
  const marcos = estreito ? 3 : 5;
  for (let k = 0; k <= marcos; k++) {
    const x = t0 + (t1 - t0) * k / marcos, d = new Date(x);
    const tx = mk('text', { x: px(x), y: m.t + ih + 18, 'text-anchor': 'middle', 'font-size': 11 });
    tx.textContent = (t1 - t0) > 3 * 365 * 864e5 ? d.getFullYear()
      : d.toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
    svg.appendChild(tx);
  }
  if (e.min < 1 && e.max > 1) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(1), y2: py(1),
      stroke: css('--line-strong'), 'stroke-width': 1, 'stroke-dasharray': '2 3' }));
    const tx = mk('text', { x: m.l + 5, y: py(1) - 5, 'font-size': 10.5, fill: css('--ink-3') });
    tx.textContent = 'P/VP = 1'; svg.appendChild(tx);
  }
  if (est.mediana != null) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(est.mediana), y2: py(est.mediana),
      stroke: css('--ink-2'), 'stroke-width': 1.2, 'stroke-dasharray': '6 4' }));
  }

  let d = '', abriu = false, ultimo = -1;
  for (let i = 0; i < datas.length; i++) {
    const v = valores[i];
    if (v == null || !isFinite(v)) { abriu = false; continue; }
    d += (abriu ? 'L' : 'M') + px(ts[i]).toFixed(1) + ' ' + py(v).toFixed(1) + ' ';
    abriu = true; ultimo = i;
  }
  svg.appendChild(mk('path', { d, fill: 'none', stroke: azul, 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));

  // Rótulos à direita: mediana, faixa e hoje, afastados para não se cobrirem.
  const marcas = [];
  if (est.mediana != null) marcas.push({ x: m.l + iw, y: py(est.mediana), cor: css('--ink-2'),
                                         texto: `mediana ${num(est.mediana, 2)}` });
  if (hoje) {
    const xh = px(Date.parse(hoje.data)), yh = py(hoje.valor);
    if (ultimo >= 0) {
      svg.appendChild(mk('line', { x1: px(ts[ultimo]), y1: py(valores[ultimo]), x2: xh, y2: yh,
        stroke: azul, 'stroke-width': 1.5, 'stroke-dasharray': '3 3' }));
    }
    svg.appendChild(mk('circle', { cx: xh, cy: yh, r: 4.5, fill: azul,
      stroke: css('--surface-1'), 'stroke-width': 2 }));
    marcas.push({ x: m.l + iw, y: yh, cor: azul, texto: `hoje ${num(hoje.valor, 2)}`, forte: true });
  } else if (ultimo >= 0) {
    svg.appendChild(mk('circle', { cx: px(ts[ultimo]), cy: py(valores[ultimo]), r: 4, fill: azul }));
    marcas.push({ x: m.l + iw, y: py(valores[ultimo]), cor: azul,
                  texto: num(valores[ultimo], 2), forte: true });
  }
  afastar(marcas);
  marcas.forEach(x => {
    const tx = mk('text', { x: x.x + 8, y: x.y + 3.5, 'font-size': 11, fill: x.cor,
      'font-weight': x.forte ? 600 : 400 });
    tx.textContent = x.texto; svg.appendChild(tx);
  });

  const cursor = mk('line', { y1: m.t, y2: m.t + ih, stroke: css('--line-strong'),
    'stroke-width': 1, 'stroke-dasharray': '3 3', opacity: 0 });
  svg.appendChild(cursor);
  const bola = mk('circle', { r: 4, fill: azul, stroke: css('--surface-1'), 'stroke-width': 2, opacity: 0 });
  svg.appendChild(bola);
  const area = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  svg.appendChild(area);
  const n = datas.length;
  area.addEventListener('mousemove', (ev) => {
    const cx = ev.clientX - svg.getBoundingClientRect().left;
    const fator = (svg.viewBox.baseVal.width || w) / svg.clientWidth;
    const alvo = t0 + ((cx * fator - m.l) / iw) * (t1 - t0);
    let lo = 0, hi = n - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (ts[mid] < alvo) lo = mid + 1; else hi = mid; }
    if (lo > 0 && Math.abs(ts[lo - 1] - alvo) < Math.abs(ts[lo] - alvo)) lo--;
    const v = valores[lo];
    cursor.setAttribute('x1', px(ts[lo])); cursor.setAttribute('x2', px(ts[lo]));
    cursor.setAttribute('opacity', 1);
    if (v != null && isFinite(v)) {
      bola.setAttribute('cx', px(ts[lo])); bola.setAttribute('cy', py(v)); bola.setAttribute('opacity', 1);
    } else bola.setAttribute('opacity', 0);
    mostrarTip(ev, `<b>semana de ${dataBR(datas[lo])}</b>
      <div class="r"><span>P/VP</span><span>${num(v, 2)}</span></div>`);
  });
  area.addEventListener('mouseleave', () => {
    cursor.setAttribute('opacity', 0); bola.setAttribute('opacity', 0); esconderTip();
  });
}

// ===========================================================================
// Crédito privado
// ===========================================================================
// Arquivo próprio (`credito.json`), carregado só quando a aba abre — como o
// histórico do spread. Ele traz a lista de papéis, que a primeira aba não
// precisa.
let C = null;
let estadoCredito = 'nao-pedido';     // nao-pedido | buscando | pronto | ausente
function carregarCredito() {
  if (estadoCredito !== 'nao-pedido') return;
  estadoCredito = 'buscando';
  renderCredito();
  fetch('credito.json?' + encodeURIComponent(D.meta.geradoEm || ''))
    .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
    .then(j => { C = j; estadoCredito = 'pronto'; renderCredito(); })
    .catch(() => { C = null; estadoCredito = 'ausente'; renderCredito(); });
}

const NOME_GRUPO = {
  diSpread: 'DI + spread, não isentas',
  ipcaIsenta: 'IPCA + spread, isentas',
  ipcaNaoIsenta: 'IPCA + spread, não isentas',
};
const CURTO_GRUPO = { diSpread: 'DI+', ipcaIsenta: 'IPCA isenta', ipcaNaoIsenta: 'IPCA não isenta' };
const BASE_GRUPO = { diSpread: 'sobre o DI', ipcaIsenta: 'sobre a NTN-B', ipcaNaoIsenta: 'sobre a NTN-B' };
const MOTIVO_FORA = {
  semTaxa: 'sem taxa indicativa no dia',
  resgateEmExercicio: 'com resgate antecipado já exercível',
  curta: 'com duração abaixo de meio ano',
  indexador: 'atrelados a % do DI, IGP-M ou prefixados',
  semNtnb: 'sem a NTN-B de referência no arquivo de títulos públicos',
  semCadastro: 'fora do cadastro do SND (isenção desconhecida)',
  diIsenta: 'de DI marcados como incentivados',
};

function renderCredito() {
  const box = el('creditoStatus');
  if (!box) return;
  if (estadoCredito !== 'pronto') {
    el('creditoConteudo').classList.add('hidden');
    box.classList.remove('hidden');
    box.innerHTML = estadoCredito === 'ausente'
      ? `O <code>credito.json</code> ainda não existe. Ele é gerado pelo
         <code>atualizar_mercado.py</code>, junto com o resto da aba — rode a ação
         <b>Atualizar mercado</b> no GitHub ou <code>python atualizar_mercado.py --so-credito</code>.`
      : 'Carregando os spreads de crédito…';
    return;
  }
  box.classList.add('hidden');
  el('creditoConteudo').classList.remove('hidden');
  el('creditoDemo').classList.toggle('hidden', !(C.meta && C.meta.demo));

  const h = C.hoje || {}, g = h.grupos || {};
  const cv = C.curvas;
  const ptCurva = (rating, prazo) => {
    if (!cv) return null;
    const i = cv.vertices.indexOf(prazo);
    return i < 0 ? null : cv[rating][i];
  };

  // Cartões
  const t = [];
  const gt = (k) => g[k] || {};
  t.push(tile('DI + spread · mediana', pp(gt('diSpread').mediana),
    `${gt('diSpread').n || 0} papéis não isentos · sobre o DI`));
  t.push(tile('IPCA isentas · mediana', pp(gt('ipcaIsenta').mediana),
    `${gt('ipcaIsenta').n || 0} papéis · sobre a NTN-B`));
  const bruto = (gt('ipcaIsenta').bruto || {}).mediana;
  if (bruto != null) {
    t.push(tile('Isentas · equivalente bruto', pp(bruto),
      `com IR de ${num((h.aliquotaIR || 0) * 100, 0)}% e IPCA esperado de ${taxa(h.ipcaEsperado, 2)}`));
  }
  if (cv) {
    t.push(tile('AA · 3 anos', pp(ptCurva('AA', 3)),
      `curva ANBIMA de ${dataBR(cv.data)} · AAA ${num(ptCurva('AAA', 3), 2)} · A ${num(ptCurva('A', 3), 2)}`));
  }
  el('faixaCredito').innerHTML = t.join('');

  // Tabela por grupo e faixa
  const linhasG = [];
  ['diSpread', 'ipcaIsenta', 'ipcaNaoIsenta'].forEach(k => {
    const e = g[k];
    if (!e) return;
    const isenta = k === 'ipcaIsenta';
    const lin = (rot, x, forte, brutoMed) => `<tr${forte ? ' class="total"' : ''}>
        <td class="l tk">${forte ? esc(NOME_GRUPO[k]) : ''}</td>
        <td class="l${forte ? '' : ' muted'}">${esc(rot)}</td>
        <td class="num">${x.n || '—'}</td>
        <td class="num">${pp(x.p25)}</td>
        <td class="num">${forte ? '<b>' + pp(x.mediana) + '</b>' : pp(x.mediana)}</td>
        <td class="num">${pp(x.p75)}</td>
        <td class="num">${x.duracaoMediana == null ? '—' : num(x.duracaoMediana, 1) + ' anos'}</td>
        <td class="num">${isenta ? pp(brutoMed) : '<span class="muted">—</span>'}</td>
      </tr>`;
    linhasG.push(lin('todas', e, true, (e.bruto || {}).mediana));
    (e.faixas || []).forEach(f => linhasG.push(lin(f.faixa, f, false, f.brutoMediana)));
  });
  el('tbCreditoGrupos').querySelector('tbody').innerHTML = linhasG.join('');

  const di = gt('diSpread'), is = gt('ipcaIsenta'), nao = gt('ipcaNaoIsenta');
  const partes = [];
  if (di.mediana != null && is.mediana != null) {
    partes.push(`Em ${dataBR(h.data)}, a debênture típica de DI paga
      <b>${pp(di.mediana)}</b> sobre o DI e a incentivada típica de IPCA,
      <b>${pp(is.mediana)}</b> sobre a NTN-B.`);
  }
  if (bruto != null) {
    partes.push(`Pelo equivalente bruto, a isenta típica vale o mesmo que um papel
      tributado a <b>${pp(bruto)}</b> sobre a NTN-B — é o benefício fiscal medido em
      spread, e é ele que faz o spread líquido das isentas parecer pequeno.`);
  } else {
    partes.push('Sem a inflação esperada do Focus nesta coleta, o equivalente bruto ficou de fora.');
  }
  if (nao.n != null && nao.n < 30) {
    partes.push(`As IPCA não isentas são só <b>${nao.n}</b>: o mercado de IPCA é quase
      todo incentivado, e a mediana desse grupo se mexe com a entrada ou saída de
      um papel.`);
  }
  el('notaCreditoGrupos').innerHTML = partes.join(' ');

  const fora = h.excluidos || {};
  const somaFora = Object.values(fora).reduce((a, b) => a + b, 0);
  el('notaCreditoFora').innerHTML = `Das <b>${h.total || 0}</b> debêntures do arquivo
    de ${dataBR(h.data)}, <b>${somaFora}</b> ficaram fora da conta:
    ${Object.entries(fora).map(([k, v]) => `${v} ${esc(MOTIVO_FORA[k] || k)}`).join('; ') || 'nenhuma'}.
    Nada é extrapolado, nenhum spread é carregado de um dia para o outro, e a
    tabela de papéis mostra exatamente o que entrou em cada mediana.`;

  // Curvas por rating
  if (cv) {
    linhas(el('chRating'), {
      grade: cv.vertices, eixoY: 'Spread sobre o DI (p.p.)',
      series: [
        { nome: 'AAA', rotulo: 'AAA', valores: cv.AAA, cor: css('--s1'), largura: 2.4 },
        { nome: 'AA', rotulo: 'AA', valores: cv.AA, cor: css('--s2'), largura: 2.4 },
        { nome: 'A', rotulo: 'A', valores: cv.A, cor: css('--s3'), largura: 2.4 },
      ],
    });
    const dia = ptCurva('AA', 3), diaDI = di.mediana;
    el('notaRating').innerHTML = `Curva de ${dataBR(cv.data)}. Em 3 anos: AAA
      ${pp(ptCurva('AAA', 3))}, AA ${pp(ptCurva('AA', 3))}, A ${pp(ptCurva('A', 3))}.
      ${diaDI != null && dia != null ? `A mediana das DI+ do mercado (${pp(diaDI)}, duração
      típica de ${num(di.duracaoMediana, 1)} anos) cai perto da curva AA.` : ''}
      A curva do dia sai depois do fechamento; quando ela atrasa, a tela mostra a
      mais recente e diz a data.`;
  } else {
    moldura(el('chRating'), 60);
    el('notaRating').textContent = 'A ANBIMA não devolveu a curva por rating nas últimas coletas.';
  }

  renderCreditoHistorico();
  renderPapeis();
}

// ---------------------------------------------------------------------------
// Abertura e fechamento
// ---------------------------------------------------------------------------
// Variação em pontos-base (centésimos de ponto percentual). É a unidade em que
// o mercado fala de spread de crédito: "abriu 10" é 0,10 p.p.
const bps = (v) => (v == null || !isFinite(v)) ? '—'
  : Math.abs(v) < 0.0005 ? '0 bps'
  : (v > 0 ? '+' : '') + nf(Math.abs(v) < 0.1 ? 1 : 0).format(v * 100) + ' bps';
// Menos de meio ponto-base num período inteiro é "estável", não abertura.
const ESTAVEL = 0.005;
const sentidoDe = (v) => v == null ? '' : v > ESTAVEL ? 'abriu' : v < -ESTAVEL ? 'fechou' : 'estável';

const SERIES_GRUPO = {
  diSpread: { nome: 'DI + spread, não isentas', base: 'sobre o DI' },
  ipcaIsenta: { nome: 'IPCA + spread, isentas', base: 'sobre a NTN-B' },
  ipcaIsentaBruta: { nome: 'IPCA isentas — equivalente bruto', base: 'sobre a NTN-B, como se tributada' },
  ipcaNaoIsenta: { nome: 'IPCA + spread, não isentas', base: 'sobre a NTN-B' },
};

/** Nível dos mesmos papéis: as variações diárias encadeadas para trás a
 *  partir da mediana do último pregão — o fim da linha coincide com o número
 *  dos cartões do topo. Onde a corrente quebra (dia sem variação gravada),
 *  recomeça na mediana daquele dia em vez de inventar a ligação. */
function encadear(med, vars) {
  const n = med.length, out = new Array(n).fill(null);
  let ultimo = -1;
  for (let i = n - 1; i >= 0; i--) if (med[i] != null) { ultimo = i; break; }
  if (ultimo < 0) return out;
  out[ultimo] = med[ultimo];
  for (let i = ultimo - 1; i >= 0; i--) {
    const v = vars[i + 1];
    out[i] = (out[i + 1] != null && v != null) ? out[i + 1] - v : med[i];
  }
  return out;
}

/** A série escolhida no seletor, já com nível, variação e amplitude. */
function serieCredito(H2, chave, vertice) {
  const n = (H2.datas || []).length;
  const vazio = new Array(n).fill(null);
  if (SERIES_GRUPO[chave]) {
    const med = H2[chave] || vazio, vars = H2['var_' + chave] || vazio;
    return { ...SERIES_GRUPO[chave], grupo: true, mediana: med, variacao: vars,
             nivel: encadear(med, vars),
             abriu: H2['abriu_' + chave] || null, fechou: H2['fechou_' + chave] || null };
  }
  // Curva de rating: prazo fixo, sem troca de papéis — o nível é a própria
  // curva, e a variação é a diferença para o pregão anterior que tem curva.
  const v = H2[`${chave}_${vertice}`] || vazio;
  const variacao = v.map((x, i) => {
    if (x == null) return null;
    for (let k = i - 1; k >= 0; k--) if (v[k] != null) return x - v[k];
    return null;
  });
  return { nome: `Curva ANBIMA ${chave}, ${vertice} ${vertice === '1' ? 'ano' : 'anos'}`,
           base: 'sobre o DI', grupo: false, mediana: null, nivel: v, variacao,
           abriu: null, fechou: null };
}

/** Episódios de abertura e fechamento: a série em zigue-zague. Um movimento
 *  só termina quando o spread volta pelo menos `lim` desde o extremo. */
function episodios(L, lim) {
  const idx = [];
  for (let i = 0; i < L.length; i++) if (L[i] != null && isFinite(L[i])) idx.push(i);
  if (idx.length < 2) return [];
  const eps = [];
  let dir = 0, piv = idx[0], ext = idx[0], lo = idx[0], hi = idx[0];
  for (const i of idx.slice(1)) {
    if (dir === 0) {
      if (L[i] < L[lo]) lo = i;
      if (L[i] > L[hi]) hi = i;
      if (L[i] - L[lo] >= lim - 1e-9) { dir = 1; piv = lo; ext = i; }
      else if (L[hi] - L[i] >= lim - 1e-9) { dir = -1; piv = hi; ext = i; }
      continue;
    }
    if (dir === 1) {
      if (L[i] >= L[ext]) ext = i;
      else if (L[ext] - L[i] >= lim - 1e-9) {
        eps.push({ sentido: 'abriu', de: piv, ate: ext }); piv = ext; ext = i; dir = -1;
      }
    } else {
      if (L[i] <= L[ext]) ext = i;
      else if (L[i] - L[ext] >= lim - 1e-9) {
        eps.push({ sentido: 'fechou', de: piv, ate: ext }); piv = ext; ext = i; dir = 1;
      }
    }
  }
  // O último movimento ainda não voltou o mínimo desde o extremo: não
  // terminou, mesmo que o spread tenha recuado um pouco depois do pico.
  if (dir !== 0) eps.push({ sentido: dir === 1 ? 'abriu' : 'fechou', de: piv, ate: ext,
                            emCurso: true });
  return eps;
}

/** Barras da variação de cada pregão, no mesmo eixo de datas do gráfico de
 *  linha logo acima (mesmas margens), para os dois se lerem juntos. */
function barrasNoTempo(svg, datas, valores, { altura = 170, cor, dica = null } = {}) {
  const vivos = valores.filter(v => v != null && isFinite(v));
  if (!vivos.length || datas.length < 2) {
    const h = moldura(svg, 60);
    const w = svg.viewBox.baseVal.width || 640;
    const t = mk('text', { x: w / 2, y: h / 2 + 4, 'text-anchor': 'middle', 'font-size': 12.5 });
    t.textContent = 'A variação diária aparece a partir do segundo pregão com os mesmos papéis.';
    svg.appendChild(t); return;
  }
  const h = altura, w = moldura(svg, h);
  const estreito = w < 620;
  const m = { t: 10, r: estreito ? 48 : 76, b: 30, l: estreito ? 44 : 54 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const ts = datas.map(d => Date.parse(d));
  const t0 = ts[0], t1 = ts[ts.length - 1];
  const px = (x) => m.l + ((x - t0) / (t1 - t0 || 1)) * iw;
  const e = escala([...vivos, 0]);
  const py = (v) => m.t + ih - ((v - e.min) / (e.max - e.min)) * ih;

  for (let v = e.min; v <= e.max + 1e-9; v += e.passo) {
    const y = py(v);
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: y, y2: y, class: 'gridline', 'stroke-width': 1 }));
    const tx = mk('text', { x: m.l - 9, y: y + 4, 'text-anchor': 'end', 'font-size': 11 });
    tx.textContent = nf(e.passo * 100 < 1 ? 1 : 0).format(v * 100); svg.appendChild(tx);
  }
  svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: py(0), y2: py(0),
    stroke: css('--line-strong'), 'stroke-width': 1.2 }));
  const ry = mk('text', { x: 13, y: m.t + ih / 2, 'font-size': 11.5, 'text-anchor': 'middle',
    transform: `rotate(-90 13 ${m.t + ih / 2})` });
  ry.textContent = 'bps'; svg.appendChild(ry);
  const marcos = estreito ? 3 : 5;
  for (let k = 0; k <= marcos; k++) {
    const x = t0 + (t1 - t0) * k / marcos;
    const tx = mk('text', { x: px(x), y: m.t + ih + 18, 'text-anchor': 'middle', 'font-size': 11 });
    tx.textContent = new Date(x).toLocaleDateString('pt-BR',
      { day: '2-digit', month: '2-digit', timeZone: 'UTC' });
    svg.appendChild(tx);
  }
  const passoX = iw / Math.max(datas.length - 1, 1);
  const larg = Math.max(2, Math.min(14, passoX * 0.62));
  valores.forEach((v, i) => {
    if (v == null || !isFinite(v)) return;
    const x = px(ts[i]), y0 = py(0), y1 = py(v);
    svg.appendChild(mk('rect', { x: x - larg / 2, y: Math.min(y0, y1), width: larg,
      height: Math.max(Math.abs(y1 - y0), 1), fill: cor, rx: 1.5 }));
    if (dica) {
      const alvo = mk('rect', { x: x - Math.max(larg, passoX) / 2, y: m.t,
        width: Math.max(larg, passoX), height: ih, fill: 'transparent' });
      alvo.addEventListener('mousemove', (ev) => mostrarTip(ev, dica(i)));
      alvo.addEventListener('mouseleave', esconderTip);
      svg.appendChild(alvo);
    }
  });
}

/** Variação do nível nos últimos `n` pregões com valor. */
function variacaoDosUltimos(datas, L, n) {
  const idx = [];
  for (let i = 0; i < L.length; i++) if (L[i] != null) idx.push(i);
  if (idx.length < 2) return null;
  const fim = idx[idx.length - 1];
  const ini = n == null ? idx[0] : idx[Math.max(0, idx.length - 1 - n)];
  if (ini === fim || (n != null && idx.length - 1 < n)) return null;
  return { v: L[fim] - L[ini], de: datas[ini], ate: datas[fim], pregoes: idx.indexOf(fim) - idx.indexOf(ini) };
}

function renderCreditoHistorico() {
  if (!C) return;
  const H2 = C.historico || {};
  const datas = H2.datas || [];
  const chave = estado.creditoSerie;
  const rating = ['AAA', 'AA', 'A'].includes(chave);
  const comparar = chave === 'comparar';
  el('ctlCreditoVerticeBox').classList.toggle('hidden', !rating);
  el('ctlCreditoLimiarBox').classList.toggle('hidden', comparar);
  el('boxCreditoVar').classList.toggle('hidden', comparar);
  el('boxEpisodios').classList.toggle('hidden', comparar);

  if (comparar) {
    const cores = { diSpread: css('--s1'), ipcaIsenta: css('--s2'), ipcaNaoIsenta: css('--s3') };
    const series = Object.keys(cores).map(k => {
      const sc = serieCredito(H2, k);
      return { nome: `${sc.nome} — mesmos papéis`, rotulo: CURTO_GRUPO[k], valores: sc.nivel,
               cor: cores[k], sc, k };
    });
    el('legCreditoHist').innerHTML = series.map(s => `<span><i class="linha"
        style="background:${s.cor}"></i>${esc(s.nome)}</span>`).join('');
    linhasNoTempo(el('chCreditoHist'), datas, series, {
      altura: 320, zero: true, eixoY: 'Spread (p.p.)', formato: (x) => pp(x),
    });
    el('faixaCreditoMov').innerHTML = series.map(s => {
      const r = variacaoDosUltimos(datas, s.valores, null);
      return tile(`${CURTO_GRUPO[s.k]} · desde ${r ? dataBR(r.de) : '—'}`, r ? bps(r.v) : '—',
        r ? `${sentidoDe(r.v)} em ${r.pregoes} pregões · hoje ${pp(s.valores[s.valores.length - 1])}` : '');
    }).join('');
    el('notaCreditoHist').textContent = datas.length
      ? `${datas.length} pregões, de ${dataBR(datas[0])} a ${dataBR(datas[datas.length - 1])}. `
        + 'Cada linha é o nível dos mesmos papéis, ancorado na mediana do último pregão.'
      : 'O histórico começa a se formar na primeira coleta.';
    return;
  }

  const sc = serieCredito(H2, chave, estado.creditoVertice);
  const cor = css('--s1');
  const lim = +estado.creditoLimiar || 0.05;
  const eps = episodios(sc.nivel, lim);
  const bandas = eps.map(e => ({ de: datas[e.de], ate: datas[e.ate],
    sentido: e.sentido === 'abriu' ? 'alta' : 'queda',
    rotulo: e.sentido === 'abriu' ? 'ABRIU' : 'FECHOU' }));

  const series = [{ nome: sc.grupo ? `Mesmos papéis — ${sc.base}` : `${sc.nome} — ${sc.base}`,
                    rotulo: sc.grupo ? 'mesmos' : chave,
                    valores: sc.nivel, cor }];
  if (sc.grupo) series.push({ nome: 'Mediana do dia', rotulo: 'mediana', valores: sc.mediana,
                              cor: css('--ink-3'), tracejado: true });
  el('legCreditoHist').innerHTML = series.map(s => `<span><i class="linha" style="${s.tracejado
      ? `background:repeating-linear-gradient(90deg,${s.cor} 0 5px,transparent 5px 8px)`
      : `background:${s.cor}`}"></i>${esc(s.nome)}</span>`).join('')
    + '<span><i style="background:var(--ink);opacity:.14"></i>abertura</span>'
    + '<span><i style="background:var(--ink);opacity:.05;border:1px solid var(--line)"></i>fechamento</span>';
  linhasNoTempo(el('chCreditoHist'), datas, series, {
    altura: 320, zero: sc.nivel.some(v => v != null && v < 0.15), eixoY: 'Spread (p.p.)',
    formato: (x) => pp(x), bandas,
  });

  barrasNoTempo(el('chCreditoVar'), datas, sc.variacao, {
    cor,
    dica: (i) => {
      let html = `<b>${dataBR(datas[i])}</b><div class="r"><span>${sentidoDe(sc.variacao[i])}</span>`
        + `<span>${bps(sc.variacao[i])}</span></div>`;
      if (sc.abriu && sc.abriu[i] != null) {
        html += `<div class="r"><span>papéis que abriram</span><span>${num(sc.abriu[i] * 100, 0)}%</span></div>`
          + `<div class="r"><span>papéis que fecharam</span><span>${num(sc.fechou[i] * 100, 0)}%</span></div>`;
      }
      return html;
    },
  });

  // Cartões: o último pregão, uma semana, um mês e desde o começo da série.
  const t = [];
  const ult = variacaoDosUltimos(datas, sc.nivel, 1);
  if (ult) {
    const iu = datas.indexOf(ult.ate);
    const amp = sc.abriu && sc.abriu[iu] != null
      ? ` · ${num(sc.abriu[iu] * 100, 0)}% dos papéis abriram, ${num(sc.fechou[iu] * 100, 0)}% fecharam` : '';
    t.push(tile('Último pregão', bps(ult.v), `${sentidoDe(ult.v)} em ${dataBR(ult.ate)}${amp}`));
  }
  [[5, '5 pregões'], [21, '21 pregões']].forEach(([n, rot]) => {
    const r = variacaoDosUltimos(datas, sc.nivel, n);
    if (r) t.push(tile(rot, bps(r.v), `${sentidoDe(r.v)} · desde ${dataBR(r.de)}`));
  });
  const tudo = variacaoDosUltimos(datas, sc.nivel, null);
  if (tudo) t.push(tile(`Desde ${dataBR(tudo.de)}`, bps(tudo.v),
    `${sentidoDe(tudo.v)} em ${tudo.pregoes} pregões · de ${pp(sc.nivel[datas.indexOf(tudo.de)])} `
    + `para ${pp(sc.nivel[datas.indexOf(tudo.ate)])}`));
  el('faixaCreditoMov').innerHTML = t.join('');

  // Episódios, do mais recente para o mais antigo
  const linhasEp = eps.slice().reverse().map(e => {
    const a = sc.nivel[e.de], b = sc.nivel[e.ate];
    let amp = '—';
    if (sc.abriu) {
      const v = [];
      for (let i = e.de + 1; i <= e.ate; i++) if (sc.abriu[i] != null) v.push(sc.abriu[i]);
      if (v.length) amp = num(v.reduce((x, y) => x + y, 0) / v.length * 100, 0) + '%';
    }
    const pregoes = sc.nivel.slice(e.de, e.ate + 1).filter(x => x != null).length - 1;
    return `<tr>
      <td class="l"><span class="tag">${e.sentido}</span>${e.emCurso ? ' <span class="muted">em curso</span>' : ''}</td>
      <td class="l muted">${dataBR(datas[e.de])} → ${dataBR(datas[e.ate])}</td>
      <td class="num">${pregoes}</td>
      <td class="num">${pp(a)}</td><td class="num">${pp(b)}</td>
      <td class="num"><b>${bps(b - a)}</b></td>
      <td class="num">${amp}</td></tr>`;
  });
  el('tbEpisodios').querySelector('tbody').innerHTML = linhasEp.join('')
    || `<tr><td colspan="7" class="vazio">Nenhum movimento de ${nf(0).format(lim * 100)} bps ou mais
        no período — o spread ficou parado. Diminua o mínimo para ver os menores.</td></tr>`;

  // Nota de rodapé: alcance da série e onde a variação dos mesmos papéis começa
  const partes = [];
  if (datas.length) partes.push(`${datas.length} pregões, de ${dataBR(datas[0])} a ${dataBR(datas[datas.length - 1])}.`);
  if (sc.grupo) {
    const primeira = sc.variacao.findIndex(v => v != null);
    if (primeira < 0) partes.push('Ainda não há variação dos mesmos papéis gravada — a linha cheia acompanha a mediana até a próxima coleta.');
    else if (primeira > 1) partes.push(`A variação dos mesmos papéis começa em ${dataBR(datas[primeira])}; antes disso a linha cheia segue a mediana do dia.`);
    // Quando as duas linhas se afastam, dizer quanto foi troca de papéis
    const i0 = sc.nivel.findIndex(v => v != null), i1 = sc.nivel.length - 1;
    if (i0 >= 0 && sc.mediana[i0] != null && sc.mediana[i1] != null && sc.nivel[i1] != null) {
      const dm = sc.mediana[i1] - sc.mediana[i0], dn = sc.nivel[i1] - sc.nivel[i0];
      if (Math.abs(dm - dn) >= 0.02) {
        partes.push(`Desde ${dataBR(datas[i0])} a mediana do dia andou ${bps(dm)} e os mesmos
          papéis, ${bps(dn)}: os ${bps(dm - dn).replace('+', '')} de diferença vieram de papéis
          que entraram ou saíram da conta, não de spread que mudou.`);
      }
    }
  } else {
    partes.push('A curva de um dia costuma entrar só na coleta do dia seguinte.');
  }
  el('notaCreditoHist').textContent = partes.join(' ');
}

function renderPapeis() {
  if (!C || !C.papeis) return;
  const col = {};
  (C.papeis.colunas || []).forEach((c, i) => { col[c] = i; });
  const busca = (estado.papelBusca || '').trim().toUpperCase();
  const todas = C.papeis.linhas || [];
  const varDe = (l) => col.variacao == null ? null : l[col.variacao];
  const filtradas = todas.filter(l =>
    (!estado.papelGrupo || l[col.grupo] === estado.papelGrupo) &&
    (!busca || String(l[col.codigo]).includes(busca) ||
     String(l[col.emissor] || '').toUpperCase().includes(busca)));
  // O arquivo já vem do maior spread para o menor; as outras duas ordens
  // põem no topo quem mais abriu ou fechou no último pregão (sem variação, no fim).
  if (estado.papelOrdem !== 'spread') {
    const sinal = estado.papelOrdem === 'abriu' ? -1 : 1;
    filtradas.sort((a, b) => {
      const va = varDe(a), vb = varDe(b);
      if (va == null) return vb == null ? 0 : 1;
      if (vb == null) return -1;
      return sinal * (va - vb);
    });
  }
  const LIMITE = 300;
  el('contagemPapeis').innerHTML = `<b>${filtradas.length}</b> de ${todas.length} papéis`
    + (filtradas.length > LIMITE ? ` · mostrando os ${LIMITE} primeiros; use a busca` : '');
  el('tbPapeis').querySelector('tbody').innerHTML = filtradas.slice(0, LIMITE).map(l => `<tr>
      <td class="l tk">${esc(l[col.codigo])}${l[col.resgate] ? ' <span class="tag" title="Tem cláusula de resgate ou amortização antecipada (ainda não exercível)">resgate</span>' : ''}</td>
      <td class="l cap" title="${esc(l[col.emissor])}">${esc(l[col.emissor])}</td>
      <td class="l muted">${esc(l[col.indice])}</td>
      <td class="l">${esc(CURTO_GRUPO[l[col.grupo]] || l[col.grupo])}</td>
      <td class="l muted">${dataBR(l[col.vencimento])}</td>
      <td class="num">${num(l[col.duracao], 1)}</td>
      <td class="num">${taxa(l[col.taxa], 2)}</td>
      <td class="num">${l[col.ntnb] == null ? '<span class="muted">—</span>' : taxa(l[col.ntnb], 2)}</td>
      <td class="num"><b>${pp(l[col.spread])}</b></td>
      <td class="num">${varDe(l) == null ? '<span class="muted">—</span>' : bps(varDe(l))}</td>
      <td class="num">${l[col.spreadBruto] == null ? '<span class="muted">—</span>' : pp(l[col.spreadBruto])}</td>
    </tr>`).join('') || '<tr><td colspan="11" class="vazio">Nenhum papel com esse filtro.</td></tr>';
}

function render() {
  renderTiles();
  renderJuros();
  renderSpread();
  renderSpreadHistorico();
  renderCredito();
  renderPvp();
  renderPvpPapel();
}

function trocarAba(nome) {
  document.querySelectorAll('.tabs button').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.p === nome)));
  ['juros', 'spread', 'credito', 'pvp', 'metodo'].forEach(p =>
    el('p-' + p).classList.toggle('hidden', p !== nome));
  if (nome === 'spread') carregarHistorico();
  if (nome === 'credito') carregarCredito();
  if (nome === 'pvp') carregarPvpPapeis();
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
  el('ctlCreditoSerie').addEventListener('change', (e) => {
    estado.creditoSerie = e.target.value; renderCreditoHistorico();
  });
  el('ctlCreditoVertice').addEventListener('change', (e) => {
    estado.creditoVertice = e.target.value; renderCreditoHistorico();
  });
  el('ctlCreditoLimiar').addEventListener('change', (e) => {
    estado.creditoLimiar = +e.target.value; renderCreditoHistorico();
  });
  el('ctlPapelOrdem').addEventListener('change', (e) => {
    estado.papelOrdem = e.target.value; renderPapeis();
  });
  el('ctlPapelGrupo').addEventListener('change', (e) => {
    estado.papelGrupo = e.target.value; renderPapeis();
  });
  el('ctlPapelBusca').addEventListener('input', (e) => {
    estado.papelBusca = e.target.value; renderPapeis();
  });

  el('ctlPvpPapel').addEventListener('change', (e) => escolherPapelPvp(e.target.value));
  el('ctlPvpPapel').addEventListener('input', (e) => {
    // Escolha na lista (ou código completo digitado) já troca o gráfico.
    const v = e.target.value.trim().toUpperCase();
    if (PP && PP.papeis && PP.papeis[v]) escolherPapelPvp(v);
  });
  el('ctlPvpPapelAnos').addEventListener('change', (e) => {
    estado.pvpPapelAnos = +e.target.value; renderPvpPapel();
  });
  el('tbPvp').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-tk]');
    if (tr) escolherPapelPvp(tr.dataset.tk, true);
  });

  let t = null;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 150); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);

  // Link direto para o gráfico de um papel: mercado.html#pvp=PETR4 (é o que o
  // ranking da página principal usa).
  const alvo = /^#pvp=([A-Za-z0-9]{4,6})$/.exec(location.hash || '');
  if (alvo) {
    estado.pvpPapel = alvo[1].toUpperCase();
    trocarAba('pvp');
    setTimeout(() => el('cardPvpPapel').scrollIntoView({ block: 'start' }), 50);
    return;
  }
  render();
}

iniciar();
