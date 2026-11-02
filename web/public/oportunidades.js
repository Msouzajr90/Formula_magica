/* Aba Oportunidades: a tela. A conta está em oportunidades_motor.js. */
'use strict';

const nf = (d) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : nf(d).format(v);
const sinal = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : (v > 0 ? '+' : '') + nf(d).format(v);
const el = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const dataBR = (s) => s ? String(s).slice(0, 10).split('-').reverse().join('/') : '—';

const estado = { janela: 5, k: 2, todas: false, salto: false, busca: '' };
let PP = null, DADOS = null, RES = null, RES_K = null, FM = {};

// ---------------------------------------------------------------------------
// Estado no link: #j=5&k=2&todas=1&salto=1
// ---------------------------------------------------------------------------
function lerLink() {
  const p = new URLSearchParams((location.hash || '').replace(/^#/, ''));
  const j = +p.get('j'), k = +p.get('k');
  if (Oport.JANELAS.includes(j)) estado.janela = j;
  if ([1.5, 2, 2.5, 3].includes(k)) estado.k = k;
  estado.todas = p.get('todas') === '1';
  estado.salto = p.get('salto') === '1';
}

function gravarLink() {
  const p = new URLSearchParams({ j: estado.janela, k: estado.k });
  if (estado.todas) p.set('todas', '1');
  if (estado.salto) p.set('salto', '1');
  try { history.replaceState(null, '', '#' + p.toString()); } catch (e) { /* sem histórico */ }
}

// ---------------------------------------------------------------------------
// Carga
// ---------------------------------------------------------------------------
async function iniciar() {
  lerLink();
  try {
    const [r1, r2] = await Promise.all([
      fetch('pvp_papeis.json?' + Date.now()), fetch('dados.json?' + Date.now())]);
    if (!r1.ok) throw new Error(`pvp_papeis.json respondeu ${r1.status}`);
    PP = await r1.json();
    DADOS = r2.ok ? await r2.json() : null;
  } catch (e) {
    el('loading').classList.add('hidden');
    const erro = el('erro');
    erro.innerHTML = `O histórico de P/VP por papel ainda não existe. Ele nasce no seu
      computador, com <code>pvp_papeis.bat</code> (os balanços antigos vêm da CVM, que
      recusa o robô).<br><span class="muted">${esc(e.message)}</span>`;
    erro.classList.remove('hidden');
    return;
  }
  (DADOS?.empresas || []).forEach(e => {
    if (e.ticker) FM[e.ticker] = { rank: e.rank, sel: !!e.selecionada };
  });
  (DADOS?.excluidas || []).forEach(e => {
    if (e.ticker) FM[e.ticker] = { motivo: e.motivo };
  });

  ligarControles();
  el('loading').classList.add('hidden');
  el('app').classList.remove('hidden');
  render();
}

function ligarControles() {
  const seg = (id, chave, conv) => {
    const caixa = el(id);
    caixa.querySelectorAll('button').forEach(b => {
      b.setAttribute('aria-pressed', String(conv(b.dataset.v) === estado[chave]));
      b.addEventListener('click', () => {
        estado[chave] = conv(b.dataset.v);
        caixa.querySelectorAll('button').forEach(x =>
          x.setAttribute('aria-pressed', String(x === b)));
        render();
      });
    });
  };
  seg('segJanela', 'janela', Number);
  seg('segK', 'k', Number);
  el('ckTodas').checked = estado.todas;
  el('ckSalto').checked = estado.salto;
  el('ckTodas').addEventListener('change', e => { estado.todas = e.target.checked; render(); });
  el('ckSalto').addEventListener('change', e => { estado.salto = e.target.checked; render(); });
  el('busca').addEventListener('input', e => { estado.busca = e.target.value.trim().toUpperCase(); render(); });
}

// ---------------------------------------------------------------------------
// Tela
// ---------------------------------------------------------------------------
function resultado() {
  if (!RES || RES_K !== estado.k) {
    RES = Oport.avaliar(PP, DADOS, estado.k);
    RES_K = estado.k;
  }
  return RES;
}

/** Todas as janelas com z (pelo menos duas) abaixo de `limite`. */
function todasConcordam(r, limite) {
  const zs = Oport.JANELAS.map(a => r.janelas[a])
    .filter(j => j && (estado.salto || !j.salto)).map(j => j.z);
  return zs.length >= 2 && zs.every(z => z < limite);
}

function casaBusca(t, r) {
  if (!estado.busca) return true;
  return t.includes(estado.busca) || String(r.nome || '').toUpperCase().includes(estado.busca);
}

function render() {
  gravarLink();
  const res = resultado(), a = estado.janela, k = estado.k;
  const { oportunidades, quase } = Oport.classificar(res, a, k, Oport.FAIXA_QUASE, estado.salto);
  const filtra = (lista, limite) => lista.filter(t =>
    casaBusca(t, res[t]) && (!estado.todas || todasConcordam(res[t], limite)));
  const op = filtra(oportunidades, -k);
  const qs = filtra(quase, -k + Oport.FAIXA_QUASE);

  // Os que só não entram por causa do salto.
  const saltos = estado.salto ? [] : Object.keys(res).filter(t => {
    const j = res[t].janelas[a];
    return j && j.salto && j.z < -k + Oport.FAIXA_QUASE && casaBusca(t, res[t]);
  }).sort((x, y) => res[x].janelas[a].z - res[y].janelas[a].z);

  const avaliados = Object.values(res).filter(r => r.janelas[a]).length;
  const total = Object.keys(res).length;
  const dataHoje = Object.values(res).map(r => r.data).filter(Boolean).sort().pop();

  carimbo(dataHoje);
  el('tiles').innerHTML = [
    tile('Abaixo do gatilho', op.length, `z < −${num(k, k % 1 ? 1 : 0)} em ${a} ${a === 1 ? 'ano' : 'anos'}`),
    tile('Quase lá', qs.length, `a menos de ${num(Oport.FAIXA_QUASE, 1)} desvio do gatilho`),
    tile('Avaliadas', avaliados, `de ${total} com histórico suficiente`),
    tile('Fora por salto', saltos.length, 'perto ou abaixo do gatilho'),
  ].join('');

  const rotJanela = `${a} ${a === 1 ? 'ano' : 'anos'}`;
  el('subOp').innerHTML = op.length
    ? `P/VP de hoje mais de ${num(k, k % 1 ? 1 : 0)} desvios-padrão abaixo da média de
       ${rotJanela}, do mais distante para o mais próximo. Clique no código para ver o gráfico.`
    : `Nenhuma ação está mais de ${num(k, k % 1 ? 1 : 0)} desvios abaixo da média de ${rotJanela}
       com esses filtros.`;
  el('subQuase').innerHTML = `Entre −${num(k, k % 1 ? 1 : 0)} e
    ${sinal(-k + Oport.FAIXA_QUASE, 1)} desvio: o preço-gatilho mostra quanto falta.`;

  el('tbOp').innerHTML = tabela(op, res, a, k);
  el('tbQuase').innerHTML = tabela(qs, res, a, k);
  el('sumSaltos').textContent = estado.salto
    ? 'Papéis com salto estão incluídos nas listas acima'
    : `Fora da lista por salto de patrimônio na janela (${saltos.length})`;
  el('notaSemDegraus').classList.toggle('hidden',
    Object.values(PP.papeis || {}).some(p => Array.isArray(p.v) && p.v.length));
  el('tbSaltos').innerHTML = estado.salto ? '' : tabelaSaltos(saltos, res, a);
}

function carimbo(dataHoje) {
  el('stamp').textContent = dataBR(dataHoje);
  const datas = PP.datas || [];
  const balancos = {};
  Object.values(PP.papeis || {}).forEach(p => {
    if (p.dtBalanco) balancos[p.dtBalanco] = (balancos[p.dtBalanco] || 0) + 1;
  });
  const comum = Object.entries(balancos).sort((x, y) => y[1] - x[1])[0]?.[0];
  el('stampBase').innerHTML = `P/VP semanal de ${dataBR(datas[0]).slice(3)} a
    ${dataBR(datas[datas.length - 1])} · balanços até <b>${dataBR(comum)}</b>`;

  // Balanço velho: o prazo mais longo entre duas entregas é o da DFP (90 dias
  // depois de 31/12) sobre o 3º trimestre — 6 meses. Mais que isso, há
  // balanço novo na CVM que o histórico ainda não pegou.
  const avisos = [];
  if (comum && dataHoje && (Date.parse(dataHoje) - Date.parse(comum)) / 86400000 > 185) {
    avisos.push(`<b>Os balanços estão velhos.</b> O patrimônio mais comum no histórico é de
      ${dataBR(comum)}: já há balanço mais novo na CVM. Rode <code>pvp_papeis.bat</code>
      no seu computador e publique, senão o P/VP de hoje usa um patrimônio antigo.`);
  }
  el('avisos').innerHTML = avisos.map(a => `<div class="warn">${a}</div>`).join('');
}

const tile = (k, v, h) => `<div class="tile"><div class="k">${esc(k)}</div>
  <div class="v">${esc(v)}</div><div class="h">${h}</div></div>`;

function celulaZ(j, anos, k) {
  const sel = anos === estado.janela ? ' sel' : '';
  if (!j) return `<td class="num z${sel} muted" title="Sem histórico suficiente nesta janela">—</td>`;
  const cls = j.z < -k ? ' dispara' : (j.z < -k + Oport.FAIXA_QUASE ? ' quase' : '');
  const s = j.salto && !estado.salto ? ' muted' : '';
  const tit = `Média geométrica ${num(j.mediaGeo)} · ${j.n} semanas · percentil ${num(100 * j.percentil, 1)}%`
    + (j.salto ? ` · salto: ${textoSalto(j.salto).replace(/<[^>]+>/g, '')}` : '');
  return `<td class="num z${cls}${sel}${s}" title="${esc(tit)}">${sinal(j.z)}${j.salto ? ' <span class="salto">⚠</span>' : ''}</td>`;
}

function celulaFM(t) {
  const f = FM[t];
  if (!f) return '<td class="l opc muted fm">—</td>';
  if (f.motivo) return `<td class="l opc muted fm" title="${esc(f.motivo)}">fora</td>`;
  return `<td class="l opc fm${f.sel ? ' ok' : ''}" title="${f.sel ? 'Entre as selecionadas da fórmula mágica' : 'No ranking, fora da seleção'}">#${esc(f.rank)}${f.sel ? ' ✓' : ''}</td>`;
}

function tabela(lista, res, a, k) {
  const cab = `<thead><tr>
    <th class="l">Ativo</th>
    <th>P/VP hoje</th><th class="opc">Média ${a}a</th><th>P/VP-gatilho</th>
    <th>Preço</th><th>Preço-gatilho</th>
    ${Oport.JANELAS.map(x => `<th class="${x === a ? 'sel' : ''}">z ${x}a</th>`).join('')}
    <th class="opc">Percentil</th><th class="l">Desde</th><th class="l opc" title="Posição no ranking da fórmula mágica (aba Ações)">Rank FM</th>
  </tr></thead>`;
  if (!lista.length) return cab + '<tbody><tr><td colspan="13" class="vazio">Nenhuma.</td></tr></tbody>';
  return cab + '<tbody>' + lista.map(t => {
    const r = res[t], j = r.janelas[a];
    const desde = j.desde
      ? `${dataBR(j.desde.data)} <span class="muted">(${j.desde.semanas} sem.)</span>` : '—';
    const falta = r.preco && j.precoGatilho ? j.precoGatilho / r.preco - 1 : null;
    return `<tr>
      <td class="l"><a class="tk tk-link" href="mercado.html#pvp=${encodeURIComponent(t)}"
          title="Ver o histórico de P/VP de ${esc(t)}">${esc(t)}</a>
        <div class="nm2" title="${esc(r.nome || '')}">${esc(r.nome || '')}</div></td>
      <td class="num"><b>${num(r.pvp)}</b></td>
      <td class="num opc">${num(j.mediaGeo)}</td>
      <td class="num">${num(j.gatilho)}</td>
      <td class="num">${num(r.preco)}</td>
      <td class="num" title="${falta == null ? '' : esc(`${sinal(100 * falta, 1)}% contra o preço de hoje`)}">${num(j.precoGatilho)}</td>
      ${Oport.JANELAS.map(x => celulaZ(r.janelas[x], x, k)).join('')}
      <td class="num opc">${num(100 * j.percentil, 1)}%</td>
      <td class="l">${desde}</td>
      ${celulaFM(t)}
    </tr>`;
  }).join('') + '</tbody>';
}

function textoSalto(s) {
  const f = `<span class="muted">(${s.para > s.de ? '×' : '÷'}${num(s.fator, 1)})</span>`;
  return s.tipo === 'patrimonio'
    ? `patrimônio por ação de R$ ${num(s.de)} para R$ ${num(s.para)} no balanço que entrou em ${dataBR(s.data)} ${f}`
    : `P/VP de ${num(s.de)} para ${num(s.para)} na semana de ${dataBR(s.data)} ${f}`;
}

function tabelaSaltos(lista, res, a) {
  const cab = `<thead><tr><th class="l">Ativo</th>
    <th>P/VP hoje</th><th>z ${a}a</th><th class="l">Salto na janela</th></tr></thead>`;
  if (!lista.length) return cab + '<tbody><tr><td colspan="4" class="vazio">Nenhum.</td></tr></tbody>';
  return cab + '<tbody>' + lista.map(t => {
    const r = res[t], j = r.janelas[a], s = j.salto;
    return `<tr>
      <td class="l"><a class="tk tk-link" href="mercado.html#pvp=${encodeURIComponent(t)}">${esc(t)}</a>
        <div class="nm2" title="${esc(r.nome || '')}">${esc(r.nome || '')}</div></td>
      <td class="num">${num(r.pvp)}</td>
      <td class="num">${sinal(j.z)}</td>
      <td class="l">${textoSalto(s)}</td>
    </tr>`;
  }).join('') + '</tbody>';
}

iniciar();
