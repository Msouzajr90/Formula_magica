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
  const bruto = (max - min) / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 4, 5, 10].map(m => m * mag).find(p => p >= bruto) || mag * 10;
  let lo = Math.floor(min / passo) * passo;
  let hi = Math.ceil(max / passo) * passo;
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
                       formato = null } = {}) {
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
  const m = { t: 16, r: estreito ? 48 : 76, b: 40, l: estreito ? 44 : 54 };
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
// O vértice padrão é 5 anos, não 10. Na amostra de 21 anos o prefixado
// brasileiro alcançava 10 anos em apenas 38% dos pregões — a linha nominal de
// 10 anos é um tracejado cheio de falhas, e falha não é um bom padrão. Em 5
// anos o dado existe em 93% do período.
const estado = { pvpAnos: 0, spreadVertice: '5.0', spreadAnos: 0 };
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

  const faixa = [];
  [[2, 'nominal'], [5, 'nominal'], [10, 'nominal'], [5, 'real'], [10, 'real'], [20, 'real']]
    .forEach(([p, tipo]) => {
      const v = naGrade(tipo === 'nominal' ? hoje.spreadNominal : hoje.spreadReal, p);
      if (v == null) return;
      faixa.push(tile(`${tipo === 'nominal' ? 'Nominal' : 'Real'} ${p} anos`, pp(v, 2),
        tipo === 'nominal' ? 'pré − Treasury' : 'NTN-B − TIPS'));
    });
  el('faixaSpread').innerHTML = faixa.join('');

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

function renderSpreadHistorico() {
  const caixa = el('histSpread');
  if (!caixa) return;
  if (!H) {
    el('chHistSpread').textContent = '';
    el('chHistNivel').textContent = '';
    el('histStatus').textContent = {
      'nao-pedido': '',
      'buscando': 'Carregando 21 anos de pregões…',
      'ausente': 'O arquivo spread_historico.json ainda não existe. Ele é gerado '
               + 'junto com o mercado.json — rode a ação Atualizar mercado no GitHub.',
    }[estadoHistorico] || '';
    return;
  }

  const v = estado.spreadVertice;
  const temNominal = (H.nominal || {})[v] !== undefined;
  const series = [];
  if (temNominal) series.push({ nome: `Nominal ${parseFloat(v)} anos (pré − Treasury)`,
    rotulo: 'nominal', valores: H.nominal[v], cor: css('--s1') });
  if ((H.real || {})[v] !== undefined) series.push({ nome: `Real ${parseFloat(v)} anos (NTN-B − TIPS)`,
    rotulo: 'real', valores: H.real[v], cor: css('--s2') });

  const r = recortar(H.datas, series, estado.spreadAnos);
  linhasNoTempo(el('chHistSpread'), r.datas, r.series, {
    altura: 320, zero: true, eixoY: 'Diferença (p.p.)',
    formato: (x) => pp(x, 2),
  });

  // O nível brasileiro, no mesmo eixo de tempo e em gráfico separado. Dois
  // eixos verticais no mesmo desenho é a maneira mais fácil de sugerir uma
  // relação que os dados não têm; dois gráficos empilhados dizem a mesma
  // coisa sem inventar nada.
  const nivel = [];
  if ((H.brasilPre || {})[v] !== undefined) nivel.push({ nome: `Pré ${parseFloat(v)} anos`,
    rotulo: 'pré', valores: H.brasilPre[v], cor: css('--s1') });
  if ((H.brasilNtnb || {})[v] !== undefined) nivel.push({ nome: `NTN-B ${parseFloat(v)} anos`,
    rotulo: 'NTN-B', valores: H.brasilNtnb[v], cor: css('--s2') });
  const rn = recortar(H.datas, nivel, estado.spreadAnos);
  linhasNoTempo(el('chHistNivel'), rn.datas, rn.series, {
    altura: 240, eixoY: 'Taxa brasileira (% a.a.)',
    formato: (x) => taxa(x, 2),
  });

  const comDado = (series[0] ? series[0].valores : []).filter(x => x != null).length;
  el('histStatus').textContent =
    `${H.datas.length} pregões no arquivo, de ${dataBR(H.datas[0])} a ${dataBR(H.datas[H.datas.length - 1])}`
    + (temNominal && comDado < H.datas.length
       ? ` · a linha nominal tem ${H.datas.length - comDado} dias sem dado, em que não havia prefixado tão longo em oferta`
       : '');
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
  el('ctlPvpAnos').addEventListener('change', (e) => {
    estado.pvpAnos = +e.target.value; renderPvp();
  });

  let t = null;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 150); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);

  render();
}

iniciar();
