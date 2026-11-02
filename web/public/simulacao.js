/* Aba Simulação — tela.
 *
 * O cálculo inteiro está em simulacao_motor.js (conferido contra o Python
 * pelos testes). Aqui: carregar a base, montar a carteira, mandar para o
 * motor (num Web Worker, para a tela não travar) e desenhar o resultado.
 *
 * A configuração mora no endereço da página: qualquer simulação pode ser
 * guardada como favorito ou mandada por link, sem nada salvo em servidor.
 */
'use strict';

const PASTA = 'precos/';
const el = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ===========================================================================
// Formatação
// ===========================================================================
const nf = (d = 1) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const ok = (v) => v != null && isFinite(v);
const pct = (v, d = 1) => (ok(v) ? nf(d).format(v * 100) + '%' : '—');
const pctS = (v, d = 1) => (ok(v) ? (v > 0 ? '+' : '') + nf(d).format(v * 100) + '%' : '—');
const pp = (v, d = 1) => (ok(v) ? (v > 0 ? '+' : '') + nf(d).format(v * 100) + ' p.p.' : '—');
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
function cor(v) { return !ok(v) ? '' : (v > 0 ? 'up' : (v < 0 ? 'down' : '')); }
const CLASSE = { acao: 'ação', fii: 'FII', etf: 'ETF', bdr: 'BDR', outro: 'outro' };
const pregoesTxt = (n) => {
  if (n == null) return '—';
  if (n < 42) return `${n} pregões`;
  const meses = n / 21;
  return meses < 24 ? `${nf(0).format(meses)} meses` : `${nf(1).format(n / 252)} anos`;
};

// ===========================================================================
// Estado
// ===========================================================================
let IND = null;                 // precos/indice.json
const ATIVO = new Map();        // ticker -> entrada do índice
const SERIE = new Map();        // ticker -> {i0, r: Float64Array}
let IBOV = null, CDI = null;

const estado = {
  ativos: [], modo: 'manual', alvo: 'minvar', volAlvo: 0.15, teto: 0.15,
  rebal: 'nenhum', custoBps: 15, inicio: null, fim: null,
};

async function json(caminho) {
  const r = await fetch(caminho, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${caminho}: HTTP ${r.status}`);
  return r.json();
}

async function serie(t) {
  if (SERIE.has(t)) return SERIE.get(t);
  const s = Motor.lerSerie(await json(PASTA + t + '.json'));
  SERIE.set(t, s);
  return s;
}

// ===========================================================================
// Carga
// ===========================================================================
async function iniciar() {
  try {
    IND = await json(PASTA + 'indice.json');
  } catch (e) {
    el('loading').classList.add('hidden');
    const er = el('erro');
    er.classList.remove('hidden');
    er.innerHTML = `A base de preços ainda não existe (<code>precos/indice.json</code>).<br>
      Rode a ação <b>Atualizar preços</b> no GitHub — a primeira execução baixa tudo desde 2010.`;
    return;
  }
  for (const a of IND.ativos) ATIVO.set(a.t, a);
  [IBOV, CDI] = await Promise.all([
    json(PASTA + IND.bench.IBOV.arquivo).then(Motor.lerSerie),
    json(PASTA + IND.bench.CDI.arquivo).then(Motor.lerSerie),
  ]);

  const P = IND.pregoes;
  el('stamp').textContent = dataBR(P[P.length - 1]);
  el('stampBase').textContent = `${IND.ativos.length} ativos na base · desde ${dataBR(P[0])}`;
  el('txCorte').textContent = dinheiro(IND.corteLiquidez);
  if (IND.demo) el('baseDemo').classList.remove('hidden');
  el('lista').innerHTML = IND.ativos.map(a =>
    `<option value="${a.t}">${esc(a.nome)} · ${CLASSE[a.classe] || a.classe}</option>`).join('');
  el('inDe').min = el('inAte').min = P[0];
  el('inDe').max = el('inAte').max = P[P.length - 1];

  // estado vindo do link
  if (location.search.length > 1) {
    const e = Motor.decodificarEstado(location.search.slice(1));
    Object.assign(estado, e);
    const fora = estado.ativos.filter(a => !ATIVO.has(a.t)).map(a => a.t);
    estado.ativos = estado.ativos.filter(a => ATIVO.has(a.t));
    if (fora.length) mensagem(`${fora.join(', ')} ${fora.length > 1 ? 'não estão' : 'não está'} na base; ${fora.length > 1 ? 'ficaram' : 'ficou'} de fora.`, true);
  }
  await Promise.all(estado.ativos.map(a => serie(a.t)));

  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  ligarControles();
  refletirControles();
  renderAtivos();
  agendar(0);
}

// ===========================================================================
// Carteira
// ===========================================================================
function mensagem(txt, ruim = false) {
  const m = el('msgEntrada');
  m.innerHTML = txt;
  m.className = 'msg' + (ruim ? ' ruim' : '');
  m.classList.toggle('hidden', !txt);
}

async function adicionar(texto) {
  const pedidos = String(texto || '').toUpperCase().split(/[\s,;]+/)
    .map(t => t.replace(/[^A-Z0-9]/g, '')).filter(Boolean);
  if (!pedidos.length) return;
  const problemas = [];
  const novos = [];
  for (const t of pedidos) {
    if (estado.ativos.some(a => a.t === t) || novos.includes(t)) continue;
    if (ATIVO.has(t)) { novos.push(t); continue; }
    const rec = IND.recusados && IND.recusados[t];
    if (rec && rec.motivo) problemas.push(`<b>${t}</b>: o Yahoo não tem cotação com esse código.`);
    else if (rec) problemas.push(`<b>${t}</b> está fora da base: a maior liquidez desde 2010 foi
      ${dinheiro(rec.liqMax)}/dia, abaixo do corte de ${dinheiro(IND.corteLiquidez)}.`);
    else problemas.push(`<b>${t}</b> não está na base. Para incluir, acrescente o código em
      <code>simulacao/tickers_extras.txt</code> e rode <code>Atualizar preços</code>.`);
  }
  try { await Promise.all(novos.map(serie)); }
  catch (e) { problemas.push('Falha ao baixar a série: ' + esc(e.message)); }
  for (const t of novos) if (SERIE.has(t)) estado.ativos.push({ t, peso: null });
  mensagem(problemas.join('<br>'), problemas.length > 0);
  el('novo').value = '';
  renderAtivos();
  agendar();
}

function renderAtivos() {
  const P = IND.pregoes;
  const tb = el('tbAtivos').querySelector('tbody');
  const manual = estado.modo === 'manual';
  tb.innerHTML = estado.ativos.map((a, i) => {
    const e = ATIVO.get(a.t) || {};
    const ini = P[e.i0 - 1], fim = P[e.i0 + e.n - 1];
    const vivo = e.i0 + e.n === P.length;
    const saltos = (e.saltos || []).map(([d, v]) => `${dataBR(d)} ${pctS(v, 0)}`);
    return `<tr>
      <td class="l"><span class="tk">${a.t}</span> <span class="classe">${CLASSE[e.classe] || ''}</span>
        ${saltos.length ? `<div class="salto" title="Variação diária acima de 40%: pode ser verdade ou desdobramento não ajustado pelo Yahoo. Confira.\n${saltos.join('\n')}">⚠ ${saltos.length > 1 ? saltos.length + ' saltos' : saltos[0]}</div>` : ''}</td>
      <td class="l nm opc" title="${esc(e.nome)}">${esc(e.nome)}</td>
      <td class="num">${dataBR(ini)} a ${vivo ? 'hoje' : dataBR(fim)}</td>
      <td class="num opc">${dinheiro(e.liq)}</td>
      <td class="num colPeso"><input type="number" min="0" max="100" step="0.5" data-i="${i}"
          value="${a.peso != null ? +(a.peso * 100).toFixed(2) : ''}" placeholder="igual"></td>
      <td><button class="rm" data-i="${i}" title="Tirar ${a.t}">×</button></td>
    </tr>`;
  }).join('');
  el('vazio').classList.toggle('hidden', estado.ativos.length > 0);
  el('caixaAtivos').classList.toggle('hidden', !estado.ativos.length);
  document.querySelectorAll('.colPeso').forEach(c => c.classList.toggle('hidden', !manual));

  const informados = estado.ativos.filter(a => a.peso != null);
  const soma = informados.reduce((s, a) => s + a.peso, 0);
  const brancos = estado.ativos.length - informados.length;
  el('somaPesos').innerHTML = manual && estado.ativos.length
    ? `<b>${pct(soma, 1)}</b>${brancos ? `<br><span class="muted" style="font-size:11px">${brancos} em branco: ${pct(Math.max(1 - soma, 0) / brancos, 1)} cada</span>` : ''}`
    : '';
  el('rodapeAtivos').colSpan = innerWidth <= 640 ? 2 : 4;
  el('rodapeAtivos').innerHTML = !estado.ativos.length ? '' : manual
    ? `${estado.ativos.length} ativo(s). Peso em branco divide o que falta para 100% em partes iguais.
       <button class="btn sec" id="btIguais" style="padding:3px 9px;font-size:12px;margin-left:6px">Pesos iguais</button>`
    : `${estado.ativos.length} ativo(s). Os pesos saem do Markowitz em cada data.`;

  tb.querySelectorAll('input[type=number]').forEach(inp => inp.addEventListener('input', () => {
    const v = inp.value === '' ? null : Math.max(+inp.value, 0) / 100;
    estado.ativos[+inp.dataset.i].peso = isFinite(v) ? v : null;
    renderSoma();
    agendar();
  }));
  tb.querySelectorAll('.rm').forEach(b => b.addEventListener('click', () => {
    estado.ativos.splice(+b.dataset.i, 1);
    renderAtivos();
    agendar();
  }));
  const bi = el('btIguais');
  if (bi) bi.addEventListener('click', () => {
    estado.ativos.forEach(a => { a.peso = null; });
    renderAtivos();
    agendar();
  });
}

function renderSoma() {
  // só o rodapé: redesenhar a tabela inteira tiraria o foco do campo
  const informados = estado.ativos.filter(a => a.peso != null);
  const soma = informados.reduce((s, a) => s + a.peso, 0);
  const brancos = estado.ativos.length - informados.length;
  el('somaPesos').innerHTML = `<b>${pct(soma, 1)}</b>${brancos
    ? `<br><span class="muted" style="font-size:11px">${brancos} em branco: ${pct(Math.max(1 - soma, 0) / brancos, 1)} cada</span>` : ''}`;
}

// ===========================================================================
// Controles
// ===========================================================================
function refletirControles() {
  document.querySelectorAll('#segModo button').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.v === estado.modo)));
  const mk = estado.modo === 'markowitz';
  document.querySelectorAll('.soMk').forEach(x => x.classList.toggle('hidden', !mk));
  document.querySelectorAll('.soVol').forEach(x => x.classList.toggle('hidden', !mk || estado.alvo !== 'volalvo'));
  el('selAlvo').value = estado.alvo;
  el('inVol').value = +(estado.volAlvo * 100).toFixed(1);
  el('inTeto').value = +(estado.teto * 100).toFixed(1);
  el('selReb').value = estado.rebal;
  el('inCusto').value = estado.custoBps;
  el('inDe').value = estado.inicio || '';
  el('inAte').value = estado.fim || '';
}

function ligarControles() {
  el('btAdd').addEventListener('click', () => adicionar(el('novo').value));
  el('novo').addEventListener('keydown', (e) => { if (e.key === 'Enter') adicionar(el('novo').value); });
  document.querySelectorAll('#segModo button').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.v === estado.modo)));
  const mk = estado.modo === 'markowitz';
  document.querySelectorAll('.soMk').forEach(x => x.classList.toggle('hidden', !mk));
  document.querySelectorAll('.soVol').forEach(x => x.classList.toggle('hidden', !mk || estado.alvo !== 'volalvo'));
  el('selAlvo').value = estado.alvo;
  el('inVol').value = +(estado.volAlvo * 100).toFixed(1);
  el('inTeto').value = +(estado.teto * 100).toFixed(1);
  el('selReb').value = estado.rebal;
  el('inCusto').value = estado.custoBps;
  el('inDe').value = estado.inicio || '';
  el('inAte').value = estado.fim || '';
}

function ligarControles() {
  el('btAdd').addEventListener('click', () => adicionar(el('novo').value));
  el('novo').addEventListener('keydown', (e) => { if (e.key === 'Enter') adicionar(el('novo').value); });
  // escolher na lista do datalist dispara 'input' com o valor completo
  el('novo').addEventListener('input', () => {
    const v = el('novo').value.toUpperCase().trim();
    if (ATIVO.has(v) && document.activeElement === el('novo')
        && [...el('lista').options].some(o => o.value === v)) {
      // só adiciona sozinho se o texto bate exatamente com um código da base
      // e veio de uma escolha (o valor tem o tamanho de um código inteiro)
      if (/^[A-Z0-9][A-Z0-9]{3}\d{1,2}$/.test(v) && v.length >= 5 && el('novo').dataset.ultimo !== v) {
        el('novo').dataset.ultimo = v;
      }
    }
  });
  document.querySelectorAll('#segModo button').forEach(b => b.addEventListener('click', () => {
    estado.modo = b.dataset.v;
    refletirControles(); renderAtivos(); agendar();
  }));
  el('selAlvo').addEventListener('change', () => { estado.alvo = el('selAlvo').value; refletirControles(); agendar(); });
  el('inVol').addEventListener('input', () => { const v = +el('inVol').value; if (v > 0) { estado.volAlvo = v / 100; agendar(); } });
  el('inTeto').addEventListener('input', () => { const v = +el('inTeto').value; if (v > 0 && v <= 100) { estado.teto = v / 100; agendar(); } });
  el('selReb').addEventListener('change', () => { estado.rebal = el('selReb').value; agendar(); });
  el('inCusto').addEventListener('input', () => { const v = +el('inCusto').value; if (v >= 0) { estado.custoBps = v; agendar(); } });
  el('inDe').addEventListener('change', () => { estado.inicio = el('inDe').value || null; agendar(); });
  el('inAte').addEventListener('change', () => { estado.fim = el('inAte').value || null; agendar(); });
  el('atalhos').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    const anos = +b.dataset.a;
    const ult = IND.pregoes[IND.pregoes.length - 1];
    if (!anos) estado.inicio = null;
    else {
      const d = new Date(ult + 'T00:00:00Z');
      d.setUTCFullYear(d.getUTCFullYear() - anos);
      estado.inicio = d.toISOString().slice(0, 10);
    }
    estado.fim = null;
    refletirControles(); agendar();
  }));
  el('btLink').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(location.href); el('status').textContent = 'Link copiado.'; }
    catch { prompt('Copie o link:', location.href); }
  });
  window.addEventListener('resize', () => { if (ULTIMO) desenharGraficos(ULTIMO); });
}

// ===========================================================================
// Execução (Web Worker)
// ===========================================================================
let trabalhador = null, ocupado = false, pedido = 0, temporizador = null, ULTIMO = null;

function novoTrabalhador() {
  try {
    const w = new Worker('simulacao_worker.js');
    w.onmessage = (ev) => { ocupado = false; if (ev.data.id === pedido) mostrar(ev.data.res); };
    w.onerror = () => { trabalhador = null; };
    return w;
  } catch { return null; }
}

function agendar(espera = 350) {
  clearTimeout(temporizador);
  temporizador = setTimeout(rodar, espera);
}

function rodar() {
  history.replaceState(null, '', estado.ativos.length ? '?' + Motor.codificar(estado) : location.pathname);
  if (!estado.ativos.length) {
    el('resultado').classList.add('hidden');
    el('status').textContent = '';
    return;
  }
  const dados = {
    pregoes: IND.pregoes, ibov: IBOV, cdi: CDI,
    series: Object.fromEntries(estado.ativos.map(a => [a.t, SERIE.get(a.t)])),
  };
  const cfg = JSON.parse(JSON.stringify(estado));
  pedido++;
  const pesado = estado.modo === 'markowitz' && estado.alvo !== 'minvar' && estado.rebal === 'mensal';
  el('status').textContent = pesado ? 'Calculando… (Markowitz mensal leva alguns segundos)' : 'Calculando…';
  if (ocupado && trabalhador) { trabalhador.terminate(); trabalhador = null; }
  if (!trabalhador) trabalhador = novoTrabalhador();
  if (trabalhador) {
    ocupado = true;
    trabalhador.postMessage({ id: pedido, dados, cfg });
  } else {
    const id = pedido;
    setTimeout(() => { const r = Motor.simular(dados, cfg); if (id === pedido) mostrar(r); }, 10);
  }
}

// ===========================================================================
// Resultado
// ===========================================================================
function mostrar(r) {
  const caixa = el('resultado');
  const av = el('avisos');
  if (r.erro) {
    caixa.classList.remove('hidden');
    av.classList.remove('hidden');
    av.innerHTML = `<b>Não deu para simular:</b> ${esc(r.erro)}.` +
      (r.avisos && r.avisos.length ? '<br>' + r.avisos.map(esc).join('<br>') : '');
    caixa.querySelectorAll('section, .tiles').forEach(s => s.classList.add('hidden'));
    el('status').textContent = '';
    ULTIMO = null;
    return;
  }
  caixa.querySelectorAll('section, .tiles').forEach(s => s.classList.remove('hidden'));
  caixa.classList.remove('hidden');
  ULTIMO = r;
  av.classList.toggle('hidden', !r.avisos.length);
  av.innerHTML = r.avisos.length ? '<b>Atenção.</b><ul style="margin:6px 0 0;padding-left:18px">'
    + r.avisos.map(a => `<li>${esc(a).replace(/\d{4}-\d{2}-\d{2}/g, dataBR)}</li>`).join('') + '</ul>' : '';
  el('status').textContent = `Simulado de ${dataBR(r.inicio)} a ${dataBR(r.fim)} · ${pregoesTxt(r.datas.length)}`;

  renderTiles(r);
  renderMetricas(r);
  renderPorAtivo(r);
  renderPesos(r);
  renderCorrelacao(r);
  renderMensal(r);
  desenharGraficos(r);
}

function renderTiles(r) {
  const m = r.metricas, b = r.metricasIbov, c = r.metricasCdi;
  const t = (k, v, h) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="h">${h}</div></div>`;
  el('tiles').innerHTML = [
    t('Retorno ao ano', pct(m.anual), `Ibovespa <b>${pct(b.anual)}</b> · CDI <b>${pct(c.anual)}</b>`),
    t('Volatilidade', pct(m.vol), `Ibovespa <b>${pct(b.vol)}</b>`),
    t('Sharpe', num(m.sharpe), `Ibovespa <b>${num(b.sharpe)}</b>`),
    t('Queda máxima', pct(m.mdd), `Ibovespa <b>${pct(b.mdd)}</b>`),
    t('Beta', num(m.beta), 'contra o Ibovespa'),
    t('Alfa ao ano', pctS(m.alfa), 'acima do que o beta explica'),
  ].join('');
}

function renderMetricas(r) {
  const m = r.metricas, b = r.metricasIbov, c = r.metricasCdi;
  const dd = (x) => x.drawdown || {};
  const queda = (x) => {
    const d = dd(x);
    if (!d.vale) return '—';
    return `${dataBR(d.pico)} → ${dataBR(d.vale)}`;
  };
  const rec = (x) => {
    const d = dd(x);
    if (!d.vale) return '—';
    return d.recuperacao ? pregoesTxt(d.pregoesRecuperacao) : 'não recuperou';
  };
  const L = [
    ['Retorno total', pctS(m.total), pctS(b.total), pctS(c.total)],
    ['Retorno ao ano', pct(m.anual), pct(b.anual), pct(c.anual), 'composto, 252 pregões por ano'],
    ['Volatilidade ao ano', pct(m.vol), pct(b.vol), pct(c.vol), 'desvio-padrão dos retornos diários × √252', true],
    ['Sharpe', num(m.sharpe), num(b.sharpe), '—', '(retorno ao ano − CDI ao ano) ÷ volatilidade'],
    ['Sortino', num(m.sortino), num(b.sortino), '—', 'como o Sharpe, mas só a volatilidade dos dias abaixo do CDI'],
    ['Queda máxima', pct(m.mdd), pct(b.mdd), '—', 'maior queda de um pico até o vale seguinte', true],
    ['Do pico ao vale', queda(m), queda(b), '—'],
    ['Tempo para recuperar', rec(m), rec(b), '—', 'do vale até voltar ao pico anterior'],
    ['Maior período abaixo do pico', pregoesTxt(dd(m).maiorSubmerso), pregoesTxt(dd(b).maiorSubmerso), '—'],
    ['Beta', num(m.beta), '1,00', '—', 'quanto a carteira anda quando o Ibovespa anda 1', true],
    ['Alfa ao ano', pctS(m.alfa), '—', '—', 'retorno acima do previsto pelo beta (Jensen)'],
    ['Correlação com o Ibovespa', num(m.correlacaoIbov), '1,00', '—'],
    ['Tracking error', pct(m.te), '—', '—', 'volatilidade da diferença diária para o Ibovespa'],
    ['Information ratio', num(m.ir), '—', '—', 'diferença média para o Ibovespa ÷ tracking error'],
    ['Captura de alta', pct(m.capturaAlta, 0), '100%', '—', 'nos meses em que o Ibovespa subiu, quanto da alta a carteira pegou'],
    ['Captura de baixa', pct(m.capturaBaixa, 0), '100%', '—', 'nos meses em que caiu, quanto da queda a carteira levou'],
    ['VaR 95% (1 dia)', pct(m.var95, 2), pct(b.var95, 2), '—', 'em 1 de cada 20 pregões a perda foi maior que isto', true],
    ['CVaR 95% (1 dia)', pct(m.cvar95, 2), pct(b.cvar95, 2), '—', 'perda média nesses piores 5% dos pregões'],
    ['VaR 99% (1 dia)', pct(m.var99, 2), pct(b.var99, 2), '—', 'em 1 de cada 100 pregões'],
    ['CVaR 99% (1 dia)', pct(m.cvar99, 2), pct(b.cvar99, 2), '—'],
    ['Meses positivos', pct(m.mesesPositivos, 0), pct(b.mesesPositivos, 0), '—', '', true],
    ['Melhor mês', m.melhorMes ? `${pctS(m.melhorMes.v)} <span class="muted">${mesBR(m.melhorMes.mes)}</span>` : '—',
      b.melhorMes ? `${pctS(b.melhorMes.v)} <span class="muted">${mesBR(b.melhorMes.mes)}</span>` : '—', '—'],
    ['Pior mês', m.piorMes ? `${pctS(m.piorMes.v)} <span class="muted">${mesBR(m.piorMes.mes)}</span>` : '—',
      b.piorMes ? `${pctS(b.piorMes.v)} <span class="muted">${mesBR(b.piorMes.mes)}</span>` : '—', '—'],
    ['Custos de negociação', pct(r.custos, 2), '—', '—', 'soma, em % do capital inicial', true],
    ['Giro ao ano', r.nRebalances ? pct(r.giroAnual, 0) : '—', '—', '—', 'quanto da carteira foi trocado por ano nos rebalanceamentos'],
    ['Rebalanceamentos', String(r.nRebalances), '—', '—'],
    ['Pregões', nf(0).format(m.dias), nf(0).format(b.dias), nf(0).format(c.dias)],
  ];
  el('tbMetricas').querySelector('tbody').innerHTML = L.map(([k, a, bb, cc, nota, sep]) =>
    `<tr class="${sep ? 'sep' : ''}"><td class="l">${k}${nota ? `<small>${nota}</small>` : ''}</td>
     <td class="num"><b>${a}</b></td><td class="num muted">${bb}</td><td class="num muted">${cc}</td></tr>`).join('');
}

function renderPorAtivo(r) {
  const linhas = r.porAtivo.slice().sort((a, b) => b.contribRetorno - a.contribRetorno);
  el('tbPorAtivo').querySelector('tbody').innerHTML = linhas.map(a => `<tr>
    <td class="l tk">${a.t}</td>
    <td class="num">${pct(a.pesoInicial)}</td><td class="num">${pct(a.pesoMedio)}</td><td class="num">${pct(a.pesoFinal)}</td>
    <td class="num ${cor(a.contribRetorno)}">${pp(a.contribRetorno)}</td>
    <td class="num">${pct(a.contribRisco)}</td>
    <td class="num ${cor(a.anual)}">${pct(a.anual)}</td><td class="num">${pct(a.vol)}</td>
    <td class="num">${num(a.beta)}</td><td class="num">${pct(a.mdd)}</td></tr>`).join('')
    + `<tr class="total"><td class="l">Custos</td><td></td><td></td><td></td>
       <td class="num down">${pp(-r.custos)}</td><td colspan="5"></td></tr>
       <tr><td class="l"><b>Carteira</b></td><td></td><td></td><td></td>
       <td class="num"><b>${pctS(r.metricas.total)}</b></td><td class="num">100%</td>
       <td class="num"><b>${pct(r.metricas.anual)}</b></td><td class="num">${pct(r.metricas.vol)}</td>
       <td class="num">${num(r.metricas.beta)}</td><td class="num">${pct(r.metricas.mdd)}</td></tr>`;
}

/* Fundo de célula: um matiz só, mais forte quanto maior o valor (sequencial).
 * O texto continua na cor de texto — a cor do fundo não carrega o número. */
const fundo = (v, max, variavel = '--s1') =>
  `background:color-mix(in srgb, var(${variavel}) ${Math.round(Math.min(Math.abs(v) / (max || 1), 1) * 55)}%, transparent)`;

function renderPesos(r) {
  const mk = estado.modo === 'markowitz';
  let colunas;
  if (mk && r.composicoes.length > 1) {
    colunas = r.composicoes.map(c => ({ data: c.data, w: c.w, rot: mesBR(c.data) }));
    el('subPesos').textContent = 'Pesos-alvo que o Markowitz escolheu em cada rebalanceamento, com os 12 meses anteriores a cada data.';
  } else {
    // sem troca de alvo, o que muda é a deriva: uma foto no começo de cada
    // ano, a da compra e a do último pregão
    const vistos = new Set([r.inicio.slice(0, 4)]);
    colunas = [{ data: r.inicio, w: r.composicoes[0].w, rot: dataBR(r.inicio).slice(3) }];
    r.historicoPesos.forEach((h, i) => {
      const ano = h.data.slice(0, 4);
      const ultimo = i === r.historicoPesos.length - 1;
      if (!vistos.has(ano) && !ultimo) { vistos.add(ano); colunas.push({ ...h, rot: ano }); }
      else if (ultimo) colunas.push({ ...h, rot: dataBR(h.data).slice(3) });
    });
    el('subPesos').textContent = r.nRebalances
      ? 'Peso de cada ativo no começo de cada ano. Entre um rebalanceamento e outro os pesos andam com os preços.'
      : 'Peso de cada ativo no começo de cada ano: sem rebalancear, quem sobe ganha espaço na carteira.';
  }
  if (colunas.length > 26) {
    const passo = Math.ceil(colunas.length / 24);
    colunas = colunas.filter((c, i) => i % passo === 0 || i === colunas.length - 1);
  }
  const nomes = r.porAtivo.map(a => a.t);
  const max = Math.max(...colunas.flatMap(c => c.w));
  el('tbPesos').innerHTML = `<thead><tr><th class="l">Ativo</th>${colunas.map(c =>
    `<th>${c.rot}</th>`).join('')}</tr></thead>
    <tbody>${nomes.map((t, a) => `<tr><td class="l tk">${t}</td>${colunas.map(c => {
      const v = c.w[a];
      return `<td style="${fundo(v, max)}" title="${t} em ${dataBR(c.data)}: ${pct(v)}">${v >= 0.0005 ? nf(0).format(v * 100) : '·'}</td>`;
    }).join('')}</tr>`).join('')}</tbody>`;
}

function renderCorrelacao(r) {
  const R = r.correlacao, n = r.rotulosCorrelacao;
  // divergente: positivo azul, negativo laranja, zero sem cor
  el('tbCorr').innerHTML = `<thead><tr><th></th>${n.map(x => `<th>${x === 'Ibovespa' ? 'Ibov' : x}</th>`).join('')}</tr></thead>
    <tbody>${R.map((l, i) => `<tr><td class="l tk">${n[i]}</td>${l.map((v, j) =>
      `<td style="${i === j ? '' : fundo(v, 1, v >= 0 ? '--s1' : '--s2')}" title="${n[i]} × ${n[j]}: ${num(v)}">${i === j ? '' : num(v)}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

function renderMensal(r) {
  const m = r.metricas;
  const porAno = new Map();
  for (const x of m.mensal) {
    const [a, mm] = x.mes.split('-');
    if (!porAno.has(a)) porAno.set(a, {});
    porAno.get(a)[+mm] = x.v;
  }
  const anual = (lista) => {
    const o = new Map();
    for (const x of lista) { const a = x.mes.slice(0, 4); o.set(a, (o.get(a) ?? 1) * (1 + x.v)); }
    return o;
  };
  const ac = anual(m.mensal), ab = anual(m.mensalIbov), aC = anual(m.mensalCdi);
  const MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
  const cel = (v, cls = '') => `<td class="num ${cls} ${cor(v)}">${ok(v) ? nf(1).format(v * 100) : ''}</td>`;
  el('tbMensal').innerHTML = `<thead><tr><th class="l">Ano</th>${MES.map(x => `<th>${x}</th>`).join('')}
    <th style="border-left:1px solid var(--line-strong)">Carteira</th><th>Ibovespa</th><th>CDI</th></tr></thead>
    <tbody>${[...porAno.keys()].map(a => `<tr><td class="l tk">${a}</td>${MES.map((_, i) => cel(porAno.get(a)[i + 1])).join('')}
      ${cel(ac.get(a) - 1, 'ano')}<td class="num muted">${pct(ab.get(a) - 1)}</td><td class="num muted">${pct(aC.get(a) - 1)}</td></tr>`).join('')}</tbody>`;
}

// ===========================================================================
// Gráficos (SVG, no padrão das outras abas: um eixo só, linhas de 2px,
// grade fina, cursor com os valores de todas as séries)
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

/** Linhas no tempo. series: [{nome, cor, v: [número|null]}]. Valores em fração. */
function linhas(svg, datas, series, opts = {}) {
  svg.textContent = '';
  const w = svg.clientWidth || svg.parentNode.clientWidth || 640;
  const h = opts.altura || 340;
  const m = { t: 12, r: opts.rotuloFinal ? 74 : 16, b: 30, l: 56 };
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('height', h);
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const todos = series.flatMap(s => s.v).filter(ok);
  if (!todos.length) return;
  const base0 = opts.incluirZero !== false;
  let lo = Math.min(...todos, base0 ? 0 : Infinity), hi = Math.max(...todos, base0 ? 0 : -Infinity);
  if (opts.teto != null) hi = Math.min(hi, opts.teto);
  const e = escalaNice(lo, hi);
  const n = datas.length;
  const X = (i) => m.l + (i / Math.max(n - 1, 1)) * iw;
  const Y = (v) => m.t + ih - ((v - e.lo) / (e.hi - e.lo)) * ih;
  const fmt = opts.fmt || ((v) => nf(0).format(Math.abs(v) < 1e-9 ? 0 : v * 100) + '%');

  for (let v = e.lo; v <= e.hi + e.passo / 2; v += e.passo) {
    svg.appendChild(mk('line', { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v),
      class: 'gridline', 'stroke-width': 1, ...(Math.abs(v) < 1e-12 ? { stroke: css('--line-strong') } : {}) }));
    const t = mk('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': 11 });
    t.textContent = fmt(v); svg.appendChild(t);
  }
  // marcas de tempo: anos (ou meses, em período curto), sem sobrepor
  const anos = n > 500;
  let ultimoX = -Infinity;
  for (let i = 1; i < n; i++) {
    const vira = anos ? datas[i].slice(0, 4) !== datas[i - 1].slice(0, 4)
                      : datas[i].slice(0, 7) !== datas[i - 1].slice(0, 7);
    if (!vira || X(i) - ultimoX < 46) continue;
    ultimoX = X(i);
    svg.appendChild(mk('line', { x1: X(i), x2: X(i), y1: m.t + ih, y2: m.t + ih + 4, stroke: css('--line-strong') }));
    const t = mk('text', { x: X(i), y: h - m.b + 17, 'text-anchor': 'middle', 'font-size': 11 });
    t.textContent = anos ? datas[i].slice(0, 4) : mesBR(datas[i]); svg.appendChild(t);
  }

  series.forEach(s => {
    let d = '', abre = true;
    s.v.forEach((v, i) => {
      if (!ok(v)) { abre = true; return; }
      const vv = opts.teto != null ? Math.min(v, opts.teto) : v;
      d += (abre ? 'M' : 'L') + X(i).toFixed(1) + ',' + Y(vv).toFixed(1);
      abre = false;
    });
    if (s.area) {
      const area = d + `L${X(n - 1)},${Y(0)}L${X(0)},${Y(0)}Z`;
      svg.appendChild(mk('path', { d: area, fill: s.cor, opacity: 0.12, stroke: 'none' }));
    }
    svg.appendChild(mk('path', { d, fill: 'none', stroke: s.cor, 'stroke-width': s.fino ? 1.5 : 2,
      'stroke-linejoin': 'round', ...(s.tracejado ? { 'stroke-dasharray': '4 3' } : {}) }));
    if (opts.rotuloFinal) {
      const ult = s.v[n - 1];
      if (ok(ult)) {
        const t = mk('text', { x: X(n - 1) + 6, y: Y(ult) + 4, 'font-size': 11.5, 'font-weight': 600 });
        t.style.fill = css('--ink');
        t.textContent = fmt(ult); svg.appendChild(t);
      }
    }
  });
  (opts.marcas || []).forEach(mc => {
    if (mc.i == null || !ok(mc.v)) return;
    svg.appendChild(mk('circle', { cx: X(mc.i), cy: Y(mc.v), r: 4.5, fill: mc.cor, stroke: css('--surface-1'), 'stroke-width': 2 }));
    // acima e à direita do ponto: embaixo ficaria em cima das datas do eixo
    const perto = X(mc.i) > m.l + iw * 0.7;
    const t = mk('text', { x: X(mc.i) + (perto ? -10 : 10), y: Y(mc.v) - 8, 'font-size': 11,
                           'text-anchor': perto ? 'end' : 'start' });
    t.style.fill = css('--ink-2');
    t.textContent = mc.texto; svg.appendChild(t);
  });

  const cursor = mk('line', { y1: m.t, y2: m.t + ih, class: 'gridline', 'stroke-width': 1, opacity: 0 });
  svg.appendChild(cursor);
  const alvo = mk('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' });
  alvo.addEventListener('mousemove', (ev) => {
    const cx = ev.offsetX * (w / (svg.clientWidth || w));
    const i = Math.max(0, Math.min(n - 1, Math.round(((cx - m.l) / iw) * (n - 1))));
    cursor.setAttribute('x1', X(i)); cursor.setAttribute('x2', X(i)); cursor.setAttribute('opacity', 1);
    mostrarTip(ev, `<b>${dataBR(datas[i])}</b>` + series.map(s =>
      `<div class="r"><span><i style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${s.cor};vertical-align:middle;margin-right:5px"></i>${s.nome}</span><span>${ok(s.v[i]) ? (opts.fmtTip || fmt)(s.v[i]) : '—'}</span></div>`).join(''));
  });
  alvo.addEventListener('mouseleave', () => { cursor.setAttribute('opacity', 0); esconderTip(); });
  svg.appendChild(alvo);
}

/** Barras horizontais a partir do zero (aceita negativos). */
function barras(svg, itens, fmt) {
  svg.textContent = '';
  const n = itens.length;
  if (!n) return;
  const alt = 20, gap = 6, m = { t: 6, r: 84, b: 6, l: 64 };
  const h = m.t + n * (alt + gap) + m.b;
  const w = svg.clientWidth || svg.parentNode.clientWidth || 420;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('height', h);
  const vals = itens.map(x => x.v).filter(ok);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const iw = Math.max(w - m.l - m.r, 60);
  const X = (v) => m.l + ((v - lo) / ((hi - lo) || 1)) * iw;
  svg.appendChild(mk('line', { x1: X(0), x2: X(0), y1: m.t, y2: h - m.b, stroke: css('--line-strong') }));
  itens.forEach((it, i) => {
    const y = m.t + i * (alt + gap);
    const x0 = Math.min(X(0), X(it.v)), lw = Math.max(Math.abs(X(it.v) - X(0)), 2);
    const b = mk('rect', { x: x0, y, width: lw, height: alt, rx: 4, fill: css('--s1') });
    b.addEventListener('mousemove', (ev) => mostrarTip(ev, `<b>${it.k}</b><div class="r"><span>${it.rot || ''}</span><span>${fmt(it.v)}</span></div>`));
    b.addEventListener('mouseleave', esconderTip);
    svg.appendChild(b);
    const r = mk('text', { x: m.l - 8, y: y + alt / 2 + 4, 'text-anchor': 'end', 'font-size': 12 });
    r.textContent = it.k; svg.appendChild(r);
    // valores numa coluna à direita: com barras negativas, o rótulo na ponta
    // da barra disputava espaço com o nome do ativo
    const vtx = mk('text', { x: w - 4, y: y + alt / 2 + 4, 'text-anchor': 'end', 'font-size': 11.5 });
    vtx.textContent = fmt(it.v);
    svg.appendChild(vtx);
  });
}

function legenda(id, itens) {
  el(id).innerHTML = itens.map(([nome, c, extra]) =>
    `<span><i class="linha" style="background:${c}"></i>${nome}${extra ? ` <b style="color:var(--ink)">${extra}</b>` : ''}</span>`).join('');
}

function acumular(r) { let v = 1; return Array.from(r, x => (v *= 1 + x) - 1); }

function desenharGraficos(r) {
  const c1 = css('--s1'), c2 = css('--s2'), c3 = css('--s3');
  const ac = acumular(r.carteira), ab = acumular(r.ibov), aC = acumular(r.cdi);
  el('subEvolucao').textContent = `Retorno acumulado desde a compra em ${dataBR(r.inicio)}, com proventos reinvestidos e custos descontados.`;
  legenda('legEvolucao', [['Carteira', c1, pctS(ac[ac.length - 1])], ['Ibovespa', c2, pctS(ab[ab.length - 1])],
    ['CDI', c3, pctS(aC[aC.length - 1])]]);
  linhas(el('chEvolucao'), r.datas, [
    { nome: 'CDI', cor: c3, v: aC }, { nome: 'Ibovespa', cor: c2, v: ab }, { nome: 'Carteira', cor: c1, v: ac },
  ], { altura: 380, fmtTip: (v) => pctS(v) });

  const ddC = Array.from(r.metricas.drawdown.serie), ddB = Array.from(r.metricasIbov.drawdown.serie);
  const iVale = r.datas.indexOf(r.metricas.drawdown.vale);
  legenda('legDrawdown', [['Carteira', c1, pct(r.metricas.mdd)], ['Ibovespa', c2, pct(r.metricasIbov.mdd)]]);
  linhas(el('chDrawdown'), r.datas, [
    { nome: 'Ibovespa', cor: c2, v: ddB, fino: true }, { nome: 'Carteira', cor: c1, v: ddC, area: true },
  ], { altura: 220, marcas: [{ i: iVale >= 0 ? iVale : null, v: ddC[iVale], cor: c1,
    texto: `${pct(r.metricas.mdd)} em ${dataBR(r.metricas.drawdown.vale)}` }] });

  const ord = r.porAtivo.slice().sort((a, b) => b.contribRetorno - a.contribRetorno);
  barras(el('chContrib'), ord.map(a => ({ k: a.t, v: a.contribRetorno, rot: 'contribuição' })), (v) => pp(v, 1));
  const ordR = r.porAtivo.slice().sort((a, b) => b.contribRisco - a.contribRisco);
  barras(el('chRisco'), ordR.map(a => ({ k: a.t, v: a.contribRisco, rot: 'da variância' })), (v) => pct(v, 1));

  const mv = r.metricas.moveis, mb = r.metricas.moveisIbov;
  legenda('legMovel', [['Carteira', c1], ['Ibovespa', c2]]);
  legenda('legMovel2', [['Carteira', c1], ['Ibovespa', c2]]);
  const temMovel = mv.ret12.some(ok);
  el('chRet12').parentNode.parentNode.parentNode.classList.toggle('hidden', !temMovel);
  if (temMovel) {
    linhas(el('chRet12'), r.datas, [{ nome: 'Ibovespa', cor: c2, v: mb.ret12 }, { nome: 'Carteira', cor: c1, v: mv.ret12 }],
      { altura: 260, fmtTip: (v) => pctS(v) });
    linhas(el('chVol12'), r.datas, [{ nome: 'Ibovespa', cor: c2, v: mb.vol12 }, { nome: 'Carteira', cor: c1, v: mv.vol12 }],
      { altura: 260 });
  }
}

iniciar();
