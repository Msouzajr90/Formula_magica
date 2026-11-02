/* Aba ETFs — tela.
 *
 * A conta está toda em etfs_motor.js (conferido contra simulacao/etfs.py pelos
 * testes). Aqui: carregar o catálogo e a base de preços, desenhar a tabela, o
 * gráfico, a correlação e a aderência, e guardar as escolhas no endereço.
 */
'use strict';

const PASTA = 'precos/';
const M = EtfMotor;
const el = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ===========================================================================
// Formatação (a mesma da Simulação)
// ===========================================================================
const nf = (d = 1) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const ok = (v) => v != null && isFinite(v);
const pct = (v, d = 1) => (ok(v) ? nf(d).format(v * 100) + '%' : '—');
const pctS = (v, d = 1) => (ok(v) ? (v > 0 ? '+' : '') + nf(d).format(v * 100) + '%' : '—');
const pp = (v, d = 2) => (ok(v) ? (v > 0 ? '+' : '') + nf(d).format(v * 100) + ' p.p.' : '—');
const num = (v, d = 2) => (ok(v) ? nf(d).format(v) : '—');
const dataBR = (s) => (s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : '—');
const mesBR = (s) => (s ? s.slice(5, 7) + '/' + s.slice(0, 4) : '—');
function dinheiro(v) {
  if (!ok(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return 'R$ ' + nf(1).format(v / 1e9) + ' bi';
  if (a >= 1e6) return 'R$ ' + nf(1).format(v / 1e6) + ' mi';
  if (a >= 1e3) return 'R$ ' + nf(0).format(v / 1e3) + ' mil';
  return 'R$ ' + nf(0).format(v);
}
const cor = (v) => (!ok(v) ? '' : (v > 0 ? 'up' : (v < 0 ? 'down' : '')));
const NOME_JANELA = { '12m': '12 meses', '3a': '3 anos', '5a': '5 anos', '10a': '10 anos', max: 'todo o histórico' };

// ===========================================================================
// Estado
// ===========================================================================
const MAX_SEL = 8;
const CORES = ['--s1', '--s2', '--s3', '--c4', '--c5', '--c6', '--c7', '--c8'];
let DADOS = null;          // {catalogo, indice, series, ibov, cdi, preparadas}
let BENCH = null;          // {ibov, cdi} completados até o fim
let R = null;              // resultado de M.avaliar
const estado = { sel: [], janela: '3a', grafico: '5a', cat: 'todas', busca: '', ord: null, dir: -1 };
const slot = new Map();    // ticker -> índice da cor; a cor segue o ETF, não a posição

function corDe(t) { return css(CORES[slot.get(t) ?? 0]); }
function darSlot(t) {
  if (slot.has(t)) return;
  const usados = new Set(slot.values());
  for (let i = 0; i < CORES.length; i++) if (!usados.has(i)) { slot.set(t, i); return; }
}

async function json(caminho) {
  const r = await fetch(caminho, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${caminho}: HTTP ${r.status}`);
  return r.json();
}

// ===========================================================================
// Carga
// ===========================================================================
async function iniciar() {
  let indice, catalogo;
  try {
    [indice, catalogo] = await Promise.all([json(PASTA + 'indice.json'), json('etfs_catalogo.json')]);
  } catch (e) {
    el('loading').classList.add('hidden');
    el('erro').classList.remove('hidden');
    el('erro').innerHTML = `Não consegui ler a base de preços (<code>precos/indice.json</code>) ou o catálogo de ETFs.<br>
      Rode a ação <b>Atualizar preços</b> no GitHub.`;
    return;
  }
  const naBase = indice.ativos.filter(a => catalogo.etfs[a.t]).map(a => a.t);
  const series = {};
  await Promise.all(naBase.map(t => json(PASTA + t + '.json')
    .then(a => { series[t] = M.lerSerie(a); }).catch(() => {})));
  const [ibov, cdi] = await Promise.all([
    json(PASTA + indice.bench.IBOV.arquivo).then(M.lerSerie),
    json(PASTA + indice.bench.CDI.arquivo).then(M.lerSerie),
  ]);
  DADOS = { catalogo, indice, series, ibov, cdi };
  DADOS.preparadas = M.prepararTodas(DADOS);
  BENCH = M.prepararBench(ibov, cdi, indice.pregoes.length - 1);

  const P = indice.pregoes;
  el('stamp').textContent = dataBR(P[P.length - 1]);
  if (indice.demo) el('baseDemo').classList.remove('hidden');

  Object.assign(estado, M.decodificar(location.search.slice(1)));
  const prontas = DADOS.preparadas.prontas;
  estado.sel = estado.sel.filter(t => prontas[t]).slice(0, MAX_SEL);
  if (!location.search.includes('s=')) {
    estado.sel = ['BOVA11', 'SMAL11', 'IVVB11', 'GOLD11', 'IMAB11', 'HASH11'].filter(t => prontas[t]);
  }
  estado.sel.forEach(darSlot);

  montarControles();
  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  recalcular();
}

// ===========================================================================
// Controles
// ===========================================================================
function montarControles() {
  const cats = DADOS.catalogo.categorias;
  el('segCat').innerHTML = `<button data-v="todas">Todas</button>` +
    Object.entries(cats).map(([k, v]) => `<button data-v="${k}">${esc(v)}</button>`).join('');
  const seg = (id, campo, depois) => {
    el(id).addEventListener('click', (ev) => {
      const b = ev.target.closest('button');
      if (!b) return;
      estado[campo] = b.dataset.v;
      depois();
    });
  };
  seg('segCat', 'cat', () => { refletir(); renderTabela(); });
  seg('segJanela', 'janela', recalcular);
  seg('segGrafico', 'grafico', () => { refletir(); renderGrafico(); });
  el('busca').addEventListener('input', () => { estado.busca = el('busca').value.trim().toLowerCase(); renderTabela(); });

  el('tbEtfs').querySelector('thead').addEventListener('click', (ev) => {
    const th = ev.target.closest('th.ord');
    if (!th) return;
    const k = th.dataset.k;
    if (estado.ord === k) estado.dir = -estado.dir;
    else { estado.ord = k; estado.dir = k === 't' ? 1 : -1; }
    renderTabela();
  });
  el('tbEtfs').querySelector('tbody').addEventListener('change', (ev) => {
    const cb = ev.target.closest('input[type=checkbox]');
    if (!cb) return;
    const t = cb.dataset.t;
    if (cb.checked) {
      if (estado.sel.length >= MAX_SEL) {
        cb.checked = false;
        el('rodapeTabela').textContent = `No máximo ${MAX_SEL} ETFs no gráfico — desmarque um antes.`;
        return;
      }
      estado.sel.push(t); darSlot(t);
    } else {
      estado.sel = estado.sel.filter(x => x !== t); slot.delete(t);
    }
    refletir(); renderTabela(); renderGrafico(); renderCorrelacao();
  });
  addEventListener('resize', () => { clearTimeout(montarControles.t); montarControles.t = setTimeout(renderGrafico, 150); });
}

function refletir() {
  for (const [id, v] of [['segCat', estado.cat], ['segJanela', estado.janela], ['segGrafico', estado.grafico]])
    el(id).querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
  const qs = M.codificar(estado);
  history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
}

function recalcular() {
  R = M.avaliar(DADOS, { janela: estado.janela });
  refletir();
  const nCat = Object.keys(DADOS.catalogo.etfs).length;
  el('stampBase').textContent = `${R.linhas.length} ETFs com preço · catálogo de ${nCat}`;
  renderTabela(); renderGrafico(); renderCorrelacao(); renderAderencia(); renderMetodo();
}

// ===========================================================================
// Tabela
// ===========================================================================
const ORDEM_CAT = (c) => Object.keys(DADOS.catalogo.categorias).indexOf(c);
function valor(l, k) {
  if (k[0] === 'r' && l.ret[k.slice(1)] !== undefined) return l.ret[k.slice(1)];
  return l[k];
}

function renderTabela() {
  const b = estado.busca;
  let ls = R.linhas.filter(l => (estado.cat === 'todas' || l.cat === estado.cat) &&
    (!b || (l.t + ' ' + l.nome + ' ' + l.indice).toLowerCase().includes(b)));
  if (estado.ord) {
    const k = estado.ord, d = estado.dir;
    ls.sort((x, y) => {
      const a = valor(x, k), c = valor(y, k);
      if (k === 't') return d * (a < c ? -1 : 1);
      if (!ok(a) && !ok(c)) return 0;
      if (!ok(a)) return 1;
      if (!ok(c)) return -1;
      return d * (a - c);
    });
  } else {
    ls.sort((x, y) => ORDEM_CAT(x.cat) - ORDEM_CAT(y.cat) || (y.liq || 0) - (x.liq || 0));
  }
  el('tbEtfs').querySelectorAll('th.ord').forEach(th => {
    if (th.dataset.k === estado.ord) th.dataset.dir = estado.dir > 0 ? 'asc' : 'desc';
    else delete th.dataset.dir;
  });
  const cats = DADOS.catalogo.categorias;
  const selecionados = new Set(estado.sel);
  const janelaTxt = NOME_JANELA[estado.janela];
  const celR = (v, cls = '') => `<td class="num ${cls} ${cor(v)}">${pctS(v)}</td>`;
  el('tbEtfs').querySelector('tbody').innerHTML = ls.map(l => {
    const avisos = [];
    if (l.lacunas.length) avisos.push('Yahoo sem cotação ' + l.lacunas.map(([a, c]) => `de ${dataBR(a)} a ${dataBR(c)}`).join(' e ') +
      ': o preço ficou parado e saltou de uma vez. Retornos que começam no meio da lacuna e o risco de períodos que a contêm ficam vazios.');
    if (l.artefatos.length) avisos.push('Desdobramento/grupamento não ajustado (virou retorno zero): ' +
      l.artefatos.map(([d, v]) => `${dataBR(d)} ${pctS(v, 0)}`).join(', '));
    const semRisco = !ok(l.vol) && l.lacunas.length ? ` title="Período com lacuna do Yahoo"` : '';
    const sel = selecionados.has(l.t);
    return `<tr class="${sel ? 'escolhido' : ''}" ${sel ? `style="--cor:${corDe(l.t)}"` : ''}>
      <td class="sel"><input type="checkbox" data-t="${l.t}" ${sel ? 'checked' : ''} aria-label="Marcar ${l.t}"></td>
      <td class="l"><span class="tk">${l.t}</span><span class="cat">${esc(cats[l.cat] || '')}</span>${avisos.length ? `<span class="aviso" title="${esc(avisos.join('\n\n'))}">⚠</span>` : ''}
        <div class="nm2" title="${esc(l.nome)} · índice: ${esc(l.indice)}">${esc(l.nome)} · ${esc(l.indice)}</div></td>
      <td class="num opc">${dinheiro(l.liq)}</td>
      ${celR(l.ret['1m'], 'grp')}${celR(l.ret.ano, 'opc')}${celR(l.ret['12m'])}${celR(l.ret['3a'])}${celR(l.ret['5a'], 'opc')}
      <td class="num grp"${semRisco}>${pct(l.vol)}</td>
      <td class="num"${semRisco}>${pct(l.mdd)}</td>
      <td class="num"${semRisco}>${num(l.sharpe)}</td>
      <td class="num opc">${num(l.corrIbov)}</td>
      <td class="num opc">${num(l.betaIbov)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="13" class="vazio">Nenhum ETF com esse filtro.</td></tr>`;
  el('contagem').innerHTML = `<b>${ls.length}</b> de ${R.linhas.length} ETFs · risco, correlação e beta em ${janelaTxt}` +
    (R.inicioRisco ? ` (desde ${dataBR(R.inicioRisco)})` : '') + ` · <b>${estado.sel.length}</b> de ${MAX_SEL} marcados`;
  el('rodapeTabela').textContent = '';
}

// ===========================================================================
// Gráfico (SVG no padrão das outras abas: um eixo, linhas de 2px, cursor)
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
  const bruto = (hi - lo) / passos || 1;
  const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 5, 10].map(f => f * mag).find(p => p >= bruto) || bruto;
  return { lo: Math.floor(lo / passo) * passo, hi: Math.ceil(hi / passo) * passo, passo };
}

function linhas(svg, datas, series, altura = 380) {
  svg.textContent = '';
  const w = svg.clientWidth || svg.parentNode.clientWidth || 640, h = altura;
  const m = { t: 12, r: 16, b: 30, l: 60 };
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('height', h);
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const todos = series.flatMap(s => s.v).filter(ok);
  if (!todos.length) return;
  const e = escalaNice(Math.min(0, ...todos), Math.max(0, ...todos));
  const n = datas.length;
  const X = (i) => m.l + (i / Math.max(n - 1, 1)) * iw;
  const Y = (v) => m.t + ih - ((v - e.lo) / (e.hi - e.lo)) * ih;
  const fmt = (v) => nf(0).format(Math.abs(v) < 1e-9 ? 0 : v * 100) + '%';
  for (let v = e.lo; v <= e.hi + e.passo / 2; v += e.passo) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v), class: 'gridline', 'stroke-width': 1,
      ...(Math.abs(v) < 1e-12 ? { stroke: css('--line-strong') } : {}) }));
    const t = mk('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = fmt(v); svg.appendChild(t);
  }
  const anos = n > 500;
  let ultimoX = -Infinity;
  for (let i = 1; i < n; i++) {
    const vira = anos ? datas[i].slice(0, 4) !== datas[i - 1].slice(0, 4) : datas[i].slice(0, 7) !== datas[i - 1].slice(0, 7);
    if (!vira || X(i) - ultimoX < 46) continue;
    ultimoX = X(i);
    svg.appendChild(mk('line', { x1: X(i), x2: X(i), y1: m.t + ih, y2: m.t + ih + 4, stroke: css('--line-strong') }));
    const t = mk('text', { x: X(i), y: h - m.b + 17, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = anos ? datas[i].slice(0, 4) : mesBR(datas[i]); svg.appendChild(t);
  }
  for (const s of series) {
    let d = '', abre = true;
    s.v.forEach((v, i) => {
      if (!ok(v)) { abre = true; return; }
      d += (abre ? 'M' : 'L') + X(i).toFixed(1) + ',' + Y(v).toFixed(1);
      abre = false;
    });
    svg.appendChild(mk('path', { d, fill: 'none', stroke: s.cor, 'stroke-width': s.fino ? 1.5 : 2,
      'stroke-linejoin': 'round', ...(s.tracejado ? { 'stroke-dasharray': '5 4' } : {}) }));
  }
  const cursor = mk('line', { y1: m.t, y2: m.t + ih, class: 'gridline', 'stroke-width': 1, opacity: 0 });
  svg.appendChild(cursor);
  const alvo = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  alvo.addEventListener('mousemove', (ev) => {
    const cx = ev.offsetX * (w / (svg.clientWidth || w));
    const i = Math.max(0, Math.min(n - 1, Math.round(((cx - m.l) / iw) * (n - 1))));
    cursor.setAttribute('x1', X(i)); cursor.setAttribute('x2', X(i)); cursor.setAttribute('opacity', 1);
    const ord = series.slice().sort((a, b) => (ok(b.v[i]) ? b.v[i] : -Infinity) - (ok(a.v[i]) ? a.v[i] : -Infinity));
    mostrarTip(ev, `<b>${dataBR(datas[i])}</b>` + ord.map(s =>
      `<div class="r"><span><i style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${s.cor};vertical-align:middle;margin-right:5px"></i>${s.nome}</span><span>${ok(s.v[i]) ? pctS(s.v[i]) : '—'}</span></div>`).join(''));
  });
  alvo.addEventListener('mouseleave', () => { cursor.setAttribute('opacity', 0); esconderTip(); });
  svg.appendChild(alvo);
}

function renderGrafico() {
  const P = DADOS.indice.pregoes, fim = P.length - 1;
  const pr = DADOS.preparadas.prontas;
  const sel = estado.sel.filter(t => pr[t]);
  const g = estado.grafico;
  const notas = [];
  // partida comum: a da janela, ou a do ETF mais novo, se ele começou depois
  let s = g === 'max' ? Math.max(...sel.map(t => pr[t].i0 - 1), 0) : M.partida(P, fim, g);
  if (g !== 'max') {
    const maisNovo = sel.reduce((a, t) => (pr[t].i0 - 1 > (a ? pr[a].i0 - 1 : -1) ? t : a), null);
    if (maisNovo && pr[maisNovo].i0 - 1 > s) {
      s = pr[maisNovo].i0 - 1;
      notas.push(`O gráfico começa em ${dataBR(P[s])}, primeiro preço do ${maisNovo}: todas as linhas partem do mesmo dia.`);
    }
  }
  const fora = sel.filter(t => !M.precoReal(pr[t], s));
  if (fora.length) notas.push(`${fora.join(', ')} fora do gráfico: o Yahoo estava sem cotação em ${dataBR(P[s])}, então não há preço de partida. Escolha uma janela que comece depois da lacuna, ou "Máximo".`);
  const usa = sel.filter(t => !fora.includes(t));
  const datas = P.slice(s, fim + 1);
  const series = [
    { nome: 'CDI', cor: css('--ink-3'), v: M.curva(BENCH.cdi, s, fim), tracejado: true, fino: true },
    { nome: 'Ibovespa', cor: css('--ink-2'), v: M.curva(BENCH.ibov, s, fim), fino: true },
    ...usa.map(t => ({ nome: t, cor: corDe(t), v: M.curva(pr[t], s, fim) })),
  ];
  if (usa.some(t => pr[t].lac.some(([a, c]) => c > s && a <= fim)))
    notas.push('Linha interrompida = lacuna do Yahoo; ela retoma no nível certo quando o preço volta.');
  const fin = (v) => { for (let i = v.length - 1; i >= 0; i--) if (ok(v[i])) return v[i]; return null; };
  el('legGrafico').innerHTML = [...series.slice(2), series[1], series[0]].map(x =>
    `<span><i class="${x.tracejado ? 'trac' : 'linha'}" style="${x.tracejado ? 'color' : 'background'}:${x.cor}"></i>${x.nome} <b style="color:var(--ink)">${pctS(fin(x.v))}</b></span>`).join('');
  el('subGrafico').textContent = `Retorno acumulado desde ${dataBR(P[s])}, com proventos reinvestidos. Ibovespa e CDI como régua.`;
  linhas(el('chGrafico'), datas, series);
  el('notaGrafico').textContent = (sel.length ? '' : 'Marque ETFs na tabela para vê-los aqui. ') + notas.join(' ');
}

// ===========================================================================
// Correlação
// ===========================================================================
function renderCorrelacao() {
  const P = DADOS.indice.pregoes, fim = P.length - 1;
  const pr = DADOS.preparadas.prontas;
  const nomes = estado.sel.filter(t => pr[t]);
  if (!nomes.length) { el('tbCorr').innerHTML = ''; el('notaCorr').textContent = 'Marque ETFs na tabela.'; return; }
  const series = [...nomes.map(t => pr[t]), BENCH.ibov];
  const rot = [...nomes, 'Ibov'];
  const s = M.partida(P, fim, estado.janela);
  const C = M.matrizCorrelacao(series, s, fim, estado.janela);
  const fundo = (v) => {
    if (!ok(v)) return '';
    const a = Math.round(Math.min(Math.abs(v), 1) * 55);
    return `background:color-mix(in srgb, var(${v >= 0 ? '--s1' : '--neg'}) ${a}%, transparent)`;
  };
  el('tbCorr').innerHTML = `<thead><tr><th class="l"></th>${rot.map(x => `<th>${x}</th>`).join('')}</tr></thead>
    <tbody>${C.map((l, i) => `<tr><td class="l tk">${rot[i]}</td>${l.map((v, j) => i === j ? '<td></td>' :
      `<td style="${fundo(v)}" title="${rot[i]} × ${rot[j]}: ${ok(v) ? num(v) : 'sem 26 semanas em comum, limpas'}">${ok(v) ? num(v) : '—'}</td>`).join('')}</tr>`).join('')}</tbody>`;
  const vazios = C.flat().filter(v => v == null).length;
  el('notaCorr').textContent = `Janela: ${NOME_JANELA[estado.janela]}${s != null && estado.janela !== 'max' ? ` (desde ${dataBR(P[s])})` : ''}; cada par usa o período em que os dois têm preço.` +
    (vazios ? ' "—": menos de 26 semanas em comum sem lacuna do Yahoo.' : '');
}

// ===========================================================================
// Aderência
// ===========================================================================
function renderAderencia() {
  const naBase = new Map(R.linhas.map(l => [l.t, l]));
  const blocos = R.grupos.map(g => {
    const linhasG = g.itens.map(i => i.vazio
      ? `<tr><td class="l tk">${i.t}</td><td colspan="4" class="l muted">histórico limpo curto demais (menos de 26 semanas)</td></tr>`
      : `<tr><td class="l tk">${i.t}</td>
          <td class="num ${cor(i.difAnual)}">${pp(i.difAnual)}</td>
          <td class="num">${pct(i.te, 2)}</td>
          <td class="num">${num(i.corr, 3)}</td>
          <td class="num muted">${i.inteira ? '' : 'desde '}${i.inteira ? NOME_JANELA[R.janela] : dataBR(i.desde)}</td></tr>`).join('');
    const refTxt = g.refT ? `${g.refT} (o de histórico mais longo${naBase.get(g.refT) ? ', ' + esc(naBase.get(g.refT).nome) : ''})` : g.ref;
    return `<h3>${esc(g.nome)}</h3><p class="refnota">Referência: ${refTxt}${g.refNota ? ' — ' + esc(g.refNota) : ''}.</p>
      <div class="scroll"><table><thead><tr><th class="l">ETF</th><th>Diferença ao ano</th><th>Tracking error</th><th>Correlação</th><th>Período</th></tr></thead>
      <tbody>${linhasG}</tbody></table></div>`;
  });
  el('ader').innerHTML = blocos.join('') || '<p class="muted">Nenhum grupo com dois ou mais ETFs na base ainda.</p>';
}

// ===========================================================================
// Método: listas de lacunas, saltos, quem ficou de fora
// ===========================================================================
function renderMetodo() {
  const cat = DADOS.catalogo;
  el('txCatalogo').textContent = `${Object.keys(cat.etfs).length} fundos, conferido em ${dataBR(cat.conferidoEm)}`;
  const comLac = R.linhas.filter(l => l.lacunas.length);
  el('txLacunas').textContent = comLac.length
    ? 'Hoje: ' + comLac.map(l => `${l.t} (${l.lacunas.map(([a, c]) => `${mesBR(a)} a ${mesBR(c)}`).join(', ')})`).join('; ') + '.'
    : 'Nenhuma na base de hoje.';
  const comArt = R.linhas.filter(l => l.artefatos.length);
  el('txArtefatos').textContent = comArt.length
    ? 'Hoje: ' + comArt.map(l => `${l.t} em ${l.artefatos.map(([d, v]) => `${dataBR(d)} (${pctS(v, 0)})`).join(', ')}`).join('; ') + '.'
    : 'Nenhum na base de hoje.';
  const rec = DADOS.indice.recusados || {};
  const semCot = [], semLiq = [], novos = [];
  for (const t of R.fora) {
    const r = rec[t];
    if (!r) novos.push(t);
    else if (/cota/i.test(r.motivo || '')) semCot.push(t);
    else semLiq.push(t);
  }
  const parte = (lista, txt) => lista.length ? `<b>${lista.length}</b> ${txt}: ${lista.join(', ')}.` : '';
  el('txFora').innerHTML = [
    parte(novos, 'ainda não testados pelo robô (entram na próxima execução de <i>Atualizar preços</i>, se tiverem liquidez)'),
    parte(semLiq, 'nunca passaram de R$ 1 milhão por dia'),
    parte(semCot, 'sem cotação no Yahoo'),
    parte(R.parados.map(p => `${p.t} (último preço ${dataBR(p.ate)})`), 'pararam de ter preço'),
  ].filter(Boolean).join(' ') || 'Todos os ETFs do catálogo estão na tabela.';
}

iniciar();
