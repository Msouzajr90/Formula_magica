/* Aba de fundos fechados — FII, Fiagro e FIP.
 *
 * O arquivo `fundos_fechados.json` já vem pronto: `baixar_fechados.py` roda no
 * PC do Marco, le os informes da CVM e grava o consolidado. Aqui nao ha calculo
 * de indicador, so filtro, ordenacao e apresentacao.
 *
 * Uma regra atravessa a tela inteira: campo ausente nao vira zero nem celula
 * vazia. FIP nao publica prazo, rentabilidade nem taxa; Fiagro tem o campo de
 * prazo inutilizavel na origem. Mostrar "—" com o motivo a um clique de
 * distancia e mais honesto que exibir um numero que nao existe.
 */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

let FUNDOS = [];
let META = {};
/* Prazo determinado primeiro — e o que distingue este universo — e, dentro de
 * cada grupo, patrimonio decrescente, garantido pela pre-ordenacao na carga e
 * pela estabilidade do sort do JavaScript. */
let ordem = { col: 'prazoOrd', dir: 1 };
let abertos = new Set();

const estado = {
  busca: '',
  tipos: new Set(['FII', 'Fiagro', 'FIP']),
  prazo: 'todos',
  anosMax: null,          // null = sem limite
  cotistasMin: 0,
  registro: new Set(),    // cetip | forabolsa | amortizando
};

/* ---------- formatacao ------------------------------------------------- */
const nd = (v, c = 0) => v == null || !isFinite(v) ? '—'
  : v.toLocaleString('pt-BR', { minimumFractionDigits: c, maximumFractionDigits: c });

const pct = (v, c = 1) => v == null || !isFinite(v) ? '—'
  : (v * 100).toLocaleString('pt-BR', { minimumFractionDigits: c, maximumFractionDigits: c }) + '%';

function dinheiro(v) {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) + ' bi';
  if (a >= 1e6) return (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi';
  if (a >= 1e3) return (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' mil';
  return nd(v);
}

const data = (s) => !s ? '—' : s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4);
const mesAno = (s) => !s ? '—' : s.slice(5, 7) + '/' + s.slice(0, 4);

/* "RESPONSABILIDADE LIMITADA", "FUNDO DE INVESTIMENTO IMOBILIARIO" e afins
 * ocupam metade do nome e nao distinguem um fundo do outro. Some da coluna,
 * fica no title e no detalhe — e a busca continua vendo o nome inteiro. */
const RUIDO = /\s*[-–—]?\s*(RESPONSABILIDADE LIMITADA|RESP\.? LIMITADA|RESP LIMITADA)\s*$/i;
function nomeCurto(n) {
  return (n || '').replace(RUIDO, '').trim() || (n || '');
}

function cnpjFmt(c) {
  if (!c || c.length !== 14) return c || '—';
  return `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}`;
}

/* Sinal com cor: variacao de cotistas e rentabilidade ganham verde/vermelho,
 * porque a direcao e o que se le primeiro nessas duas colunas. */
function comSinal(v, casas = 1) {
  if (v == null || !isFinite(v)) return '<span class="semdado">—</span>';
  const cls = v > 0 ? 'up' : (v < 0 ? 'down' : '');
  const sinal = v > 0 ? '+' : '';
  return `<span class="${cls}">${sinal}${pct(v, casas)}</span>`;
}

/* ---------- avisos por fundo ------------------------------------------- */
function atencoes(f) {
  const out = [];
  if (f.prazoVencido) out.push(['ruim', 'venceu em ' + mesAno(f.vence)]);
  if (f.prazoSuspeito) out.push(['ruim', 'data de vencimento improvável']);
  if (f.prazoConflita) out.push(['', 'rótulo conflita']);
  if (f.mesesDescartados) {
    out.push(['ruim', f.mesesDescartados + (f.mesesDescartados > 1
      ? ' meses fora do acumulado' : ' mês fora do acumulado')]);
  }
  if (f.tipo === 'FIP') out.push(['', 'informe quadrimestral']);
  if (f.cotistasVar12 != null && f.cotistasVar12 <= -0.2) {
    out.push(['ruim', 'perdeu ' + pct(-f.cotistasVar12, 0) + ' dos cotistas']);
  }
  if (f.mesesAmort > 0) out.push(['', 'amortizando']);
  return out;
}

/* ---------- filtro ------------------------------------------------------ */
function passa(f) {
  if (!estado.tipos.has(f.tipo)) return false;

  if (estado.prazo !== 'todos' && (f.prazo || 'Sem dado') !== estado.prazo) return false;

  if (estado.anosMax != null) {
    // Sem anos restantes nao passa no filtro de prazo: um fundo sem data nao
    // pode ser afirmado como "vence em ate 5 anos".
    if (f.anosRest == null || f.anosRest > estado.anosMax) return false;
  }
  if ((f.cotistas ?? 0) < estado.cotistasMin) return false;

  if (estado.registro.has('cetip') && !f.cetip) return false;
  if (estado.registro.has('forabolsa') && f.bolsa) return false;
  if (estado.registro.has('amortizando') && !(f.mesesAmort > 0)) return false;

  if (estado.busca) {
    const alvo = (f.nome + ' ' + (f.admin || '') + ' ' + f.cnpj + ' '
      + cnpjFmt(f.cnpj)).toLowerCase();
    if (!estado.busca.split(/\s+/).every((t) => alvo.includes(t))) return false;
  }
  return true;
}

/* ---------- ordenacao --------------------------------------------------- */
// 'Determinado' primeiro, depois 'Indeterminado', depois 'Sem dado' — a ordem
// de interesse, nao a alfabetica.
const PESO_PRAZO = { 'Determinado': 0, 'Indeterminado': 1, 'Sem dado': 2 };

function chave(f, col) {
  if (col === 'prazoOrd') return PESO_PRAZO[f.prazo] ?? 3;
  if (col === 'nome') return (f.nome || '').toLowerCase();
  if (col === 'inicio') return f.inicio || '';
  return f[col];
}

function ordenar(lista) {
  const c = ordem.col, d = ordem.dir;
  return lista.slice().sort((a, b) => {
    const x = chave(a, c), y = chave(b, c);
    // Ausente vai sempre para o fim, independente da direcao: o que nao tem
    // dado nao e "o menor", e so nao tem dado.
    const fx = x == null || x === '' || (typeof x === 'number' && !isFinite(x));
    const fy = y == null || y === '' || (typeof y === 'number' && !isFinite(y));
    if (fx && fy) return 0;
    if (fx) return 1;
    if (fy) return -1;
    if (typeof x === 'string') return d * x.localeCompare(y, 'pt-BR');
    return d * (x - y);
  });
}

/* ---------- desenho ----------------------------------------------------- */
function tiles(lista) {
  const det = lista.filter((f) => f.prazo === 'Determinado');
  const curto = det.filter((f) => f.anosRest != null && f.anosRest <= 3);
  const pl = lista.reduce((s, f) => s + (f.pl || 0), 0);
  const cot = lista.reduce((s, f) => s + (f.cotistas || 0), 0);
  const t = [
    ['Fundos', nd(lista.length), 'do universo filtrado'],
    ['Prazo determinado', nd(det.length), 'com data de vencimento'],
    ['Vencem em até 3 anos', nd(curto.length), 'entre os de prazo determinado'],
    ['Patrimônio somado', 'R$ ' + dinheiro(pl), 'dos fundos na lista'],
    ['Cotistas somados', nd(cot), 'posições, não pessoas'],
  ];
  $('#tiles').innerHTML = t.map(([k, v, h]) =>
    `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div>
     <div class="h">${h}</div></div>`).join('');
}

function linha(f) {
  const aten = atencoes(f).map(([cls, txt]) =>
    `<span class="aten ${cls}">${txt}</span>`).join('');
  const prazo = f.prazo === 'Determinado'
    ? `Determinado<br><span class="semdado" style="font-size:11px">${mesAno(f.vence)}</span>`
    : (f.prazo === 'Sem dado'
      ? '<span class="semdado">não publicado</span>' : (f.prazo || '—'));

  return `<tr class="linha" data-cnpj="${f.cnpj}">
    <td class="l nome" title="${f.nome.replace(/"/g, '&quot;')}"><b>${nomeCurto(f.nome)}</b>
      ${aten ? `<div class="avisos">${aten}</div>` : ''}</td>
    <td class="l"><span class="tagt ${f.tipo.toLowerCase()}">${f.tipo}</span></td>
    <td class="l">${prazo}</td>
    <td class="num">${f.anosRest == null ? '<span class="semdado">—</span>'
      : nd(f.anosRest, 1)}</td>
    <td class="num">${f.inicio ? mesAno(f.inicio) : '<span class="semdado">—</span>'}</td>
    <td class="num">${nd(f.cotistas)}</td>
    <td class="num">${comSinal(f.cotistasVar12, 0)}</td>
    <td class="num">${dinheiro(f.pl)}</td>
    <td class="num">${f.vpCota == null ? '—' : nd(f.vpCota, 2)}</td>
    <td class="num">${comSinal(f.rent12)}</td>
    <td class="num">${f.dy12 == null ? '<span class="semdado">—</span>' : pct(f.dy12)}</td>
    <td class="num">${f.amort12 ? pct(f.amort12) : '<span class="semdado">—</span>'}</td>
    <td class="num">${f.taxaAdm == null ? '<span class="semdado">—</span>'
      : pct(f.taxaAdm, 2)}</td>
  </tr>`;
}

function detalhe(f) {
  const item = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  const campos = [
    item('CNPJ', cnpjFmt(f.cnpj)),
    item('Administrador', f.admin || '—'),
    item('Público-alvo', f.publico || '—'),
    item('Competência do informe', `${mesAno(f.dtInforme)} (${f.periodo})`),
    item('Informes na série', nd(f.nInformes)),
    item('Início', data(f.inicio) + (f.idade != null ? ` · ${nd(f.idade, 1)} anos` : '')),
    item('Vencimento', f.vence ? data(f.vence) : 'não publicado'),
    item('Cotistas pessoa física', nd(f.cotistasPf)),
    item('Cotas emitidas', nd(f.cotas)),
    item('Rentabilidade no último informe', comSinal(f.rentMes, 2)),
    item('Variação do VP/cota em 12m', comSinal(f.rentVp12)),
    item('Meses com amortização', nd(f.mesesAmort)),
    item('Segmento', f.segmento || '—'),
    item('Registrado na CETIP', f.cetip == null ? '—' : (f.cetip ? 'sim' : 'não')),
    item('Negocia em bolsa', f.bolsa == null ? '—' : (f.bolsa ? 'sim' : 'não')),
  ].join('');

  let nota = '';
  if (f.tipo === 'FIP') {
    nota = `<p class="note" style="margin:10px 0 0">O informe de FIP é
      quadrimestral e não traz prazo de duração, rentabilidade nem taxa de
      administração — as colunas vazias acima são ausência na fonte, não falha
      da coleta.</p>`;
  } else if (f.mesesDescartados) {
    nota = `<p class="note" style="margin:10px 0 0">A rentabilidade acumulada
      exclui ${f.mesesDescartados} mês(es) com retorno declarado acima de 100%.
      Compare com a variação do VP/cota acima, que está em reais.</p>`;
  } else if (f.prazoConflita) {
    nota = `<p class="note" style="margin:10px 0 0">O informe declara prazo
      indeterminado e ao mesmo tempo traz data de vencimento. A tela usa a
      data.</p>`;
  }
  return `<tr class="det"><td colspan="13"><dl>${campos}</dl>${nota}</td></tr>`;
}

function desenhar() {
  const lista = ordenar(FUNDOS.filter(passa));
  tiles(lista);

  $('#tbody').innerHTML = lista.map((f) =>
    linha(f) + (abertos.has(f.cnpj) ? detalhe(f) : '')).join('')
    || `<tr><td colspan="13" class="vazio">Nenhum fundo com esses filtros.</td></tr>`;

  $$('#tbody tr.linha').forEach((tr) => {
    if (abertos.has(tr.dataset.cnpj)) tr.classList.add('aberta');
    tr.onclick = () => {
      const c = tr.dataset.cnpj;
      abertos.has(c) ? abertos.delete(c) : abertos.add(c);
      desenhar();
    };
  });

  $('#contagem').textContent =
    `${lista.length} de ${FUNDOS.length} fundos · clique numa linha para ver o detalhe`;

  $$('#tb th.ord').forEach((th) => {
    th.classList.toggle('on', th.dataset.c === ordem.col);
    th.dataset.dir = th.dataset.c === ordem.col ? (ordem.dir < 0 ? 'desc' : 'asc') : '';
  });
}

/* ---------- controles --------------------------------------------------- */
const CORTES_COTISTAS = [0, 100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000,
  15000, 20000, 30000, 40000, 50000, 75000, 1e5, 15e4, 2e5, 3e5, 5e5];

function ligarControles() {
  $('#busca').addEventListener('input', (e) => {
    estado.busca = e.target.value.trim().toLowerCase();
    desenhar();
  });

  $('#fTipo').addEventListener('click', (e) => {
    const b = e.target.closest('.opt'); if (!b) return;
    const v = b.dataset.v;
    estado.tipos.has(v) ? estado.tipos.delete(v) : estado.tipos.add(v);
    b.setAttribute('aria-pressed', estado.tipos.has(v));
    desenhar();
  });

  $('#fPrazo').addEventListener('click', (e) => {
    const b = e.target.closest('.opt'); if (!b) return;
    estado.prazo = b.dataset.v;
    $$('#fPrazo .opt').forEach((o) =>
      o.setAttribute('aria-pressed', o.dataset.v === estado.prazo));
    desenhar();
  });

  $('#fReg').addEventListener('click', (e) => {
    const b = e.target.closest('.opt'); if (!b) return;
    const v = b.dataset.v;
    estado.registro.has(v) ? estado.registro.delete(v) : estado.registro.add(v);
    b.setAttribute('aria-pressed', estado.registro.has(v));
    desenhar();
  });

  $('#fAnos').addEventListener('input', (e) => {
    const v = +e.target.value;
    estado.anosMax = v >= 31 ? null : v;
    $('#lblAnos').textContent = estado.anosMax == null ? 'qualquer prazo'
      : (v === 0 ? 'já vencido' : v + (v === 1 ? ' ano' : ' anos'));
    desenhar();
  });

  $('#fCot').addEventListener('input', (e) => {
    estado.cotistasMin = CORTES_COTISTAS[+e.target.value];
    $('#lblCot').textContent = estado.cotistasMin === 0 ? 'qualquer número'
      : nd(estado.cotistasMin) + '+';
    desenhar();
  });

  $$('#tb th.ord').forEach((th) => {
    th.addEventListener('click', () => {
      const c = th.dataset.c;
      if (ordem.col === c) ordem.dir *= -1;
      else ordem = { col: c, dir: c === 'nome' || c === 'prazoOrd' ? 1 : -1 };
      desenhar();
    });
  });
}

/* ---------- carga ------------------------------------------------------- */
function resumoDasFontes() {
  const por = META.porTipo || {};
  const partes = [];
  if (por.FIP) {
    partes.push(`Os <b>${por.FIP} FIP</b> entregam informe quadrimestral e não
      publicam prazo, rentabilidade nem taxa de administração.`);
  }
  if (por.Fiagro) {
    partes.push(`Nos <b>${por.Fiagro} Fiagro</b>, o campo de prazo da CVM vem
      preenchido com valores como "1000 ANO/ANOS" e foi descartado.`);
  }
  $('#faltaPorFonte').innerHTML = partes.join(' ');

  const avisos = META.avisos || [];
  $('#notaAvisos').innerHTML = avisos.length
    ? '<b>Da última coleta:</b> ' + avisos.map((a) =>
      a.replace(/^publicado:\s*/, '')).join(' · ')
    : '';
}

async function carregar() {
  try {
    const r = await fetch('fundos_fechados.json', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    FUNDOS = d.fundos || [];
    META = d.meta || {};
    if (!FUNDOS.length) throw new Error('arquivo sem fundos');
    FUNDOS.sort((a, b) => (b.pl || 0) - (a.pl || 0));

    $('#stamp').textContent = mesAno((META.competencia || '') + '-01');
    $('#stampFonte').textContent =
      `${nd(META.nFundos)} fundos · gerado em ${META.geradoEm || '—'}`;
    resumoDasFontes();

    $('#loading').classList.add('hidden');
    $('#app').classList.remove('hidden');
    ligarControles();
    desenhar();
  } catch (e) {
    $('#loading').classList.add('hidden');
    const erro = $('#erro');
    erro.classList.remove('hidden');
    erro.innerHTML = `<b>Não consegui carregar os dados.</b><br>
      ${e.message}<br><span class="note">O arquivo
      <code>fundos_fechados.json</code> é gerado por
      <code>baixar_fechados.py</code>, que precisa rodar num computador no
      Brasil — a CVM recusa conexões do exterior.</span>`;
  }
}

carregar();
