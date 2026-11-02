/* Motor da aba Análise técnica — cálculo puro, sem DOM.
 *
 * Lê a base de retornos da Simulação (precos/PETR4.json) e as velas
 * (precos/ohlc/PETR4.json), calcula os indicadores, a linha do painel e o
 * backtest das regras. Roda no navegador (como `TecMotor`) e no Node
 * (module.exports), onde os testes o comparam com o Python de `tecnica/`.
 *
 * Convenções (as mesmas do Python; o porquê está em tecnica/*.py)
 * ----------------------------------------------------------------
 * - `pregoes[i]` é o calendário único. Retornos {i0, r}: r[k] é o retorno do
 *   pregão i0 + k. O primeiro preço é o do pregão s0 = i0 − 1.
 * - Velas: a, x, m = (abertura, máxima, mínima) ÷ fechamento do mesmo dia − 1,
 *   em pontos-base; f = volume financeiro em R$ mil; ult = [data, fechamento
 *   bruto]. O fechamento ajustado sai dos retornos e é multiplicado para o
 *   último ponto bater com `ult` (o "gráfico ajustado").
 * - Lacuna do Yahoo (10+ retornos zero seguidos e o salto): a história se
 *   divide em trechos limpos e cada indicador recomeça em cada trecho.
 * - Médias exponenciais e Wilder começam pela média simples dos n primeiros
 *   valores; Bollinger com desvio populacional; OBV com volume financeiro.
 * - Backtest: sinal no fechamento de i, ordem na abertura de i + 1, CDI para
 *   quem dormiu fora, 15 bps por ponta, venda final; um trecho limpo só.
 */
(function (raiz) {
  'use strict';

  const DIAS_ANO = 252;
  const LACUNA_MIN = 10, LACUNA_JUNTA = 3;
  const P = {
    mmCurta: 20, mmMedia: 50, mmLonga: 200, mmeRapida: 9, mmeLenta: 21,
    ifr: 14, macd: [12, 26, 9], bollinger: [20, 2], estocastico: [14, 3, 3],
    atr: 14, adx: 14, ano: 252, donchEntrada: 55, donchSaida: 20, volRel: 20,
  };
  const JANELAS = { '1m': 21, '3m': 63, '6m': 126, '12m': 252 };
  const CUSTO_BPS = 15;
  const fin = (v) => v != null && Number.isFinite(v);

  // =========================================================================
  // Séries
  // =========================================================================
  function lerRetornos(arq) {
    const esc = arq.esc || 1e6;
    const r = new Float64Array(arq.r.length);
    for (let k = 0; k < r.length; k++) r[k] = arq.r[k] / esc;
    return { i0: arq.i0, r };
  }

  /** [[a, c, aberta]] — igual a simulacao/etfs.py `lacunas`. */
  function lacunas(i0, r) {
    const n = r.length, out = [];
    let k = 0;
    while (k < n) {
      if (r[k] !== 0) { k++; continue; }
      let j = k;
      while (j < n && r[j] === 0) j++;            // [k, j) zerados
      if (j - k >= LACUNA_MIN) {
        const item = [i0 + k, i0 + Math.min(j, n - 1), j >= n];
        const ult = out[out.length - 1];
        if (ult && item[0] - ult[1] <= LACUNA_JUNTA) { ult[1] = item[1]; ult[2] = item[2]; }
        else out.push(item);
      }
      k = j;
    }
    return out;
  }

  function trechos(s0, fim, lac) {
    const out = [];
    let ini = s0;
    for (const [a, c, aberta] of lac) {
      if (a - 1 >= ini) out.push([ini, a - 1]);
      if (aberta) return out;
      ini = c;
    }
    if (fim >= ini) out.push([ini, fim]);
    return out;
  }

  function buscar(pregoes, data) {
    let lo = 0, hi = pregoes.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (pregoes[m] < data) lo = m + 1; else hi = m; }
    return lo;
  }

  /** Retornos + velas -> vetores no calendário, de s0 a fim. */
  function preparar(retArq, velArq, pregoes) {
    const { i0, r } = lerRetornos(retArq);
    const s0 = i0 - 1, fim = i0 + r.length - 1, n = fim - s0 + 1;
    const cadj = new Float64Array(n);
    cadj[0] = 1;
    for (let k = 1; k < n; k++) cadj[k] = cadj[k - 1] * (1 + r[k - 1]);
    const a = new Float64Array(n), x = new Float64Array(n), m = new Float64Array(n);
    const vol = new Float64Array(n).fill(NaN);
    const temVela = new Uint8Array(n);
    let K = null, emReais = false;
    if (velArq) {
      const ve = velArq.esc || 1e4, vv = velArq.vesc || 1e3;
      const lo = Math.max(s0, velArq.i0), hi = Math.min(fim, velArq.i0 + velArq.a.length - 1);
      for (let i = lo; i <= hi; i++) {
        const j = i - velArq.i0, k = i - s0;
        a[k] = velArq.a[j] / ve; x[k] = velArq.x[j] / ve; m[k] = velArq.m[j] / ve;
        vol[k] = velArq.f[j] * vv; temVela[k] = 1;
      }
      const ult = velArq.ult;
      if (ult) {
        const d = buscar(pregoes, ult[0]);
        if (d < pregoes.length && pregoes[d] === ult[0] && d >= s0 && d <= fim && ult[1] > 0) {
          K = ult[1] / cadj[d - s0]; emReais = true;
        }
      }
    }
    if (K == null) K = 100 / cadj[n - 1];
    const c = new Float64Array(n), o = new Float64Array(n), h = new Float64Array(n), l = new Float64Array(n);
    for (let k = 0; k < n; k++) {
      c[k] = cadj[k] * K;
      o[k] = c[k] * (1 + a[k]); h[k] = c[k] * (1 + x[k]); l[k] = c[k] * (1 + m[k]);
    }
    const rr = new Float64Array(n); rr[0] = NaN;
    for (let k = 1; k < n; k++) rr[k] = r[k - 1];
    const lac = lacunas(i0, r);
    return { s0, fim, r: rr, c, o, h, l, a, vol, temVela, emReais, lacunas: lac, trechos: trechos(s0, fim, lac) };
  }

  // =========================================================================
  // Indicadores (vetores do trecho; NaN no aquecimento)
  // =========================================================================
  const vazio = (n) => new Float64Array(n).fill(NaN);

  function sma(x, n) {
    const out = vazio(x.length);
    for (let i = n - 1; i < x.length; i++) {
      let s = 0, ok = true;
      for (let j = i - n + 1; j <= i; j++) { if (!fin(x[j])) { ok = false; break; } s += x[j]; }
      if (ok) out[i] = s / n;
    }
    return out;
  }

  function recursiva(x, n, alfa) {
    const out = vazio(x.length);
    let f = 0;
    while (f < x.length && !fin(x[f])) f++;
    if (f + n > x.length) return out;
    let s = 0;
    for (let j = f; j < f + n; j++) s += x[j];
    let y = s / n;
    out[f + n - 1] = y;
    for (let i = f + n; i < x.length; i++) { y = y + alfa * (x[i] - y); out[i] = y; }
    return out;
  }
  const ema = (x, n) => recursiva(x, n, 2 / (n + 1));
  const wilder = (x, n) => recursiva(x, n, 1 / n);

  function ifr(c, n = P.ifr) {
    const L = c.length, g = vazio(L), p = vazio(L);
    for (let i = 1; i < L; i++) { const d = c[i] - c[i - 1]; g[i] = d > 0 ? d : 0; p[i] = d < 0 ? -d : 0; }
    const mg = wilder(g, n), mp = wilder(p, n), out = vazio(L);
    for (let i = 0; i < L; i++) {
      if (!fin(mg[i])) continue;
      if (mp[i] === 0) out[i] = mg[i] > 0 ? 100 : 50;
      else out[i] = 100 - 100 / (1 + mg[i] / mp[i]);
    }
    return out;
  }

  function desvioPop(x, i, n, media) {
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += (x[j] - media) ** 2;
    return Math.sqrt(s / n);
  }

  function bollinger(c, n = P.bollinger[0], k = P.bollinger[1]) {
    const L = c.length, meio = sma(c, n), sup = vazio(L), inf = vazio(L), pctB = vazio(L);
    for (let i = 0; i < L; i++) {
      if (!fin(meio[i])) continue;
      const dp = desvioPop(c, i, n, meio[i]);
      sup[i] = meio[i] + k * dp; inf[i] = meio[i] - k * dp;
      pctB[i] = sup[i] > inf[i] ? (c[i] - inf[i]) / (sup[i] - inf[i]) : 0.5;
    }
    return { meio, sup, inf, pctB };
  }

  function macd(c, rapida = P.macd[0], lenta = P.macd[1], sinal = P.macd[2]) {
    const er = ema(c, rapida), el = ema(c, lenta), L = c.length, linha = vazio(L);
    for (let i = 0; i < L; i++) linha[i] = er[i] - el[i];
    const sin = ema(linha, sinal), hist = vazio(L);
    for (let i = 0; i < L; i++) hist[i] = linha[i] - sin[i];
    return { linha, sinal: sin, hist };
  }

  function maxMovel(x, n) {
    const out = vazio(x.length);
    for (let i = n - 1; i < x.length; i++) {
      let v = -Infinity;
      for (let j = i - n + 1; j <= i; j++) if (x[j] > v) v = x[j];
      out[i] = v;
    }
    return out;
  }
  function minMovel(x, n) {
    const out = vazio(x.length);
    for (let i = n - 1; i < x.length; i++) {
      let v = Infinity;
      for (let j = i - n + 1; j <= i; j++) if (x[j] < v) v = x[j];
      out[i] = v;
    }
    return out;
  }
  function anterior(x) { const out = vazio(x.length); for (let i = 1; i < x.length; i++) out[i] = x[i - 1]; return out; }

  function estocastico(h, l, c, n = P.estocastico[0], k = P.estocastico[1], d = P.estocastico[2]) {
    const hh = maxMovel(h, n), ll = minMovel(l, n), L = c.length, rap = vazio(L);
    for (let i = 0; i < L; i++) {
      if (!fin(hh[i])) continue;
      rap[i] = hh[i] > ll[i] ? 100 * (c[i] - ll[i]) / (hh[i] - ll[i]) : 50;
    }
    const pk = sma(rap, k);
    return { k: pk, d: sma(pk, d) };
  }

  function trueRange(h, l, c) {
    const tr = vazio(c.length);
    for (let i = 1; i < c.length; i++)
      tr[i] = Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
    return tr;
  }
  const atr = (h, l, c, n = P.atr) => wilder(trueRange(h, l, c), n);

  function adx(h, l, c, n = P.adx) {
    const L = c.length, tr = trueRange(h, l, c), pdm = vazio(L), ndm = vazio(L);
    for (let i = 1; i < L; i++) {
      const sobe = h[i] - h[i - 1], desce = l[i - 1] - l[i];
      pdm[i] = sobe > desce && sobe > 0 ? sobe : 0;
      ndm[i] = desce > sobe && desce > 0 ? desce : 0;
    }
    const st = wilder(tr, n), sp = wilder(pdm, n), sn = wilder(ndm, n);
    const pdi = vazio(L), ndi = vazio(L), dx = vazio(L);
    for (let i = 0; i < L; i++) {
      if (!fin(st[i])) continue;
      pdi[i] = st[i] > 0 ? 100 * sp[i] / st[i] : 0;
      ndi[i] = st[i] > 0 ? 100 * sn[i] / st[i] : 0;
      const s = pdi[i] + ndi[i];
      dx[i] = s > 0 ? 100 * Math.abs(pdi[i] - ndi[i]) / s : 0;
    }
    return { adx: wilder(dx, n), diMais: pdi, diMenos: ndi };
  }

  function obv(c, vol) {
    const out = new Float64Array(c.length);
    for (let i = 1; i < c.length; i++) {
      const v = fin(vol[i]) ? vol[i] : 0;
      out[i] = out[i - 1] + Math.sign(c[i] - c[i - 1]) * v;
    }
    return out;
  }

  /** Todos os indicadores de um trecho. */
  function calcular(o, h, l, c, vol) {
    const ind = {};
    ind.mm20 = sma(c, P.mmCurta); ind.mm50 = sma(c, P.mmMedia); ind.mm200 = sma(c, P.mmLonga);
    ind.mme9 = ema(c, P.mmeRapida); ind.mme21 = ema(c, P.mmeLenta);
    const bb = bollinger(c);
    ind.bbMeio = bb.meio; ind.bbSup = bb.sup; ind.bbInf = bb.inf; ind.pctB = bb.pctB;
    ind.ifr = ifr(c);
    const md = macd(c);
    ind.macd = md.linha; ind.macdSinal = md.sinal; ind.macdHist = md.hist;
    const es = estocastico(h, l, c);
    ind.estK = es.k; ind.estD = es.d;
    ind.atr = atr(h, l, c);
    const ax = adx(h, l, c);
    ind.adx = ax.adx; ind.diMais = ax.diMais; ind.diMenos = ax.diMenos;
    ind.obv = obv(c, vol);
    ind.max52 = maxMovel(h, P.ano); ind.min52 = minMovel(l, P.ano);
    ind.donchSup = anterior(maxMovel(h, P.donchEntrada));
    ind.donchInf = anterior(minMovel(l, P.donchSaida));
    ind.volMedia = anterior(sma(vol, P.volRel));
    return ind;
  }

  /** Indicadores na série inteira, trecho a trecho. */
  function indicadores(prep) {
    const n = prep.c.length, out = {};
    for (const [ini, fim] of prep.trechos) {
      const p = ini - prep.s0, q = fim - prep.s0 + 1;
      if (q - p < 2) continue;
      const sl = (v) => v.subarray(p, q);
      const parte = calcular(sl(prep.o), sl(prep.h), sl(prep.l), sl(prep.c), sl(prep.vol));
      for (const k in parte) {
        if (!out[k]) out[k] = vazio(n);
        out[k].set(parte[k], p);
      }
    }
    return out;
  }

  // =========================================================================
  // Linha do painel
  // =========================================================================
  function regimeDesde(dif, k, p) {
    if (!fin(dif[k])) return null;
    const pos = dif[k] > 0;
    let j = k;
    while (j - 1 >= p && fin(dif[j - 1]) && (dif[j - 1] > 0) === pos) j--;
    return j - 1 >= p && fin(dif[j - 1]) ? j : null;
  }

  function resumo(prep, ind, ibov, pregoes) {
    const { s0, fim, c } = prep;
    const out = { ate: pregoes[fim], atraso: pregoes.length - 1 - fim,
                  velas: !!prep.temVela[prep.temVela.length - 1], emReais: prep.emReais };
    const tr = prep.trechos;
    if (!tr.length || tr[tr.length - 1][1] !== fim) {
      out.parado = pregoes[tr.length ? tr[tr.length - 1][1] : s0];
      return out;
    }
    const ultT = tr[tr.length - 1], p = ultT[0] - s0, k = fim - s0;
    const g = (nome) => (ind[nome] && fin(ind[nome][k]) ? ind[nome][k] : null);
    const nz = (v) => (fin(v) ? v : null);
    out.desde = ultT[0] > s0 ? pregoes[ultT[0]] : null;
    out.preco = prep.emReais ? c[k] : null;
    out.var1d = k - 1 >= p ? nz(c[k] / c[k - 1] - 1) : null;
    for (const [nome, n] of Object.entries(JANELAS)) out['r' + nome] = k - n >= p ? nz(c[k] / c[k - n] - 1) : null;
    for (const n of [20, 50, 200]) { const mm = g('mm' + n); out['dMm' + n] = mm ? nz(c[k] / mm - 1) : null; }
    const dif = vazio(c.length);
    for (let i = 0; i < c.length; i++) dif[i] = ind.mm50[i] - ind.mm200[i];
    out.tend = fin(dif[k]) ? (dif[k] > 0 ? 'alta' : 'baixa') : null;
    let j = regimeDesde(dif, k, p);
    out.tendDesde = j != null ? pregoes[s0 + j] : null;
    const hist = ind.macdHist;
    out.macdAcima = fin(hist[k]) ? hist[k] > 0 : null;
    j = regimeDesde(hist, k, p);
    out.macdDesde = j != null ? pregoes[s0 + j] : null;
    for (const nome of ['ifr', 'pctB', 'estK', 'estD', 'adx', 'diMais', 'diMenos']) out[nome] = g(nome);
    const a = g('atr');
    out.atrPct = a != null ? nz(a / c[k]) : null;
    const mx = g('max52'), mn = g('min52');
    out.dMax52 = mx ? nz(c[k] / mx - 1) : null;
    out.dMin52 = mn ? nz(c[k] / mn - 1) : null;
    out.novaMax52 = mx ? prep.h[k] >= mx : null;
    out.novaMin52 = mn ? prep.l[k] <= mn : null;
    const ds = g('donchSup');
    out.rompe55 = ds ? c[k] > ds : null;
    const vm = g('volMedia'), v = nz(prep.vol[k]);
    out.volRel = vm && v != null && vm > 0 ? nz(v / vm) : null;
    out.fr6m = null;
    const n6 = JANELAS['6m'];
    if (ibov && k - n6 >= p) {
      const a_ = fim - n6 + 1, b_ = fim;
      if (ibov.i0 <= a_ && b_ <= ibov.i0 + ibov.r.length - 1) {
        let ri = 1;
        for (let i = a_; i <= b_; i++) ri *= 1 + ibov.r[i - ibov.i0];
        out.fr6m = nz((c[k] / c[k - n6]) / ri - 1);
      }
    }
    if (!out.velas) for (const nome of ['estK', 'estD', 'adx', 'diMais', 'diMenos', 'atrPct', 'volRel']) out[nome] = null;
    return out;
  }

  // =========================================================================
  // Backtest
  // =========================================================================
  const REGRAS = {
    mm: { nome: 'Cruzamento de médias', params: { rapida: 50, lenta: 200, tipo: 's' } },
    preco_mm: { nome: 'Preço acima da média', params: { n: 200, tipo: 's' } },
    macd: { nome: 'MACD acima da linha de sinal', params: { rapida: 12, lenta: 26, sinal: 9 } },
    ifr: { nome: 'IFR: compra sobrevendido, vende sobrecomprado', params: { n: 14, baixo: 30, alto: 70 } },
    bollinger: { nome: 'Bollinger: compra abaixo da banda, vende na média', params: { n: 20, k: 2 } },
    rompimento: { nome: 'Rompimento de máxima (Donchian)', params: { entrada: 55, saida: 20 } },
  };

  const media = (c, n, tipo) => (tipo === 'e' ? ema(c, n) : sma(c, n));

  function maquina(L, pronto, entra, sai) {
    const out = vazio(L);
    let estado = null;
    for (let i = 0; i < L; i++) {
      if (!pronto(i)) continue;
      if (estado == null) estado = 0;
      if (entra(i)) estado = 1; else if (sai(i)) estado = 0;
      out[i] = estado;
    }
    return out;
  }

  function alvo(regra, p, o, h, l, c) {
    const L = c.length, out = vazio(L);
    if (regra === 'mm') {
      const f = media(c, +p.rapida, p.tipo), s = media(c, +p.lenta, p.tipo);
      for (let i = 0; i < L; i++) if (fin(f[i]) && fin(s[i])) out[i] = f[i] > s[i] ? 1 : 0;
      return out;
    }
    if (regra === 'preco_mm') {
      const m = media(c, +p.n, p.tipo);
      for (let i = 0; i < L; i++) if (fin(m[i])) out[i] = c[i] > m[i] ? 1 : 0;
      return out;
    }
    if (regra === 'macd') {
      const md = macd(c, +p.rapida, +p.lenta, +p.sinal);
      for (let i = 0; i < L; i++) if (fin(md.linha[i]) && fin(md.sinal[i])) out[i] = md.linha[i] > md.sinal[i] ? 1 : 0;
      return out;
    }
    if (regra === 'ifr') {
      const v = ifr(c, +p.n);
      return maquina(L, (i) => fin(v[i]), (i) => v[i] < +p.baixo, (i) => v[i] > +p.alto);
    }
    if (regra === 'bollinger') {
      const bb = bollinger(c, +p.n, +p.k);
      return maquina(L, (i) => fin(bb.meio[i]), (i) => c[i] < bb.inf[i], (i) => c[i] > bb.meio[i]);
    }
    if (regra === 'rompimento') {
      const sup = anterior(maxMovel(h, +p.entrada)), inf = anterior(minMovel(l, +p.saida));
      return maquina(L, (i) => fin(sup[i]) && fin(inf[i]), (i) => c[i] > sup[i], (i) => c[i] < inf[i]);
    }
    throw new Error('regra desconhecida: ' + regra);
  }

  /** CDI do último pregão sai no dia seguinte: repete a última taxa (até 10). */
  function completarCdi(cdi, fim) {
    const falta = fim - (cdi.i0 + cdi.r.length - 1);
    if (falta <= 0 || falta > 10) return cdi;
    const r = new Float64Array(cdi.r.length + falta);
    r.set(cdi.r);
    for (let k = cdi.r.length; k < r.length; k++) r[k] = cdi.r[cdi.r.length - 1];
    return { i0: cdi.i0, r };
  }

  /**
   * Backtest de uma regra. opts: {ini, fim (índices do calendário), custoBps}.
   * Devolve {s, e, ini, rp, bh, exposto, ops, alvo} ou null.
   */
  function simular(prep, regra, params, cdi, opts = {}) {
    const s0 = prep.s0;
    const fimPedido = opts.fim == null ? prep.fim : Math.min(opts.fim, prep.fim);
    let trecho = null;
    for (let t = prep.trechos.length - 1; t >= 0; t--) if (prep.trechos[t][0] <= fimPedido) { trecho = prep.trechos[t]; break; }
    if (!trecho) return null;
    const e = Math.min(fimPedido, trecho[1]);
    const iniT = opts.ini == null ? trecho[0] : Math.max(opts.ini, trecho[0]);
    if (e - iniT < 2) return null;
    const p = iniT - s0, q = e - s0 + 1;
    const sl = (v) => v.subarray(p, q);
    const alv = alvo(regra, params, sl(prep.o), sl(prep.h), sl(prep.l), sl(prep.c));
    let s = null;
    for (let i = 0; i < alv.length; i++) if (fin(alv[i])) { s = iniT + i; break; }
    if (s == null || e - s < 2) return null;
    const tau = (j) => (j < s ? 0 : alv[j - iniT]);           // alvo decidido no fechamento de j
    const custo = (opts.custoBps == null ? CUSTO_BPS : opts.custoBps) / 1e4;
    const n = e - s, rp = new Float64Array(n), bh = new Float64Array(n);
    const ops = [];
    let aberta = null, expostos = 0;
    for (let j = s + 1; j <= e; j++) {
      const k = j - s0, idx = j - s - 1;
      const noite = (1 + prep.r[k]) * (1 + prep.a[k]), dia = 1 / (1 + prep.a[k]);
      const tN = tau(j - 2), tD = tau(j - 1);
      const jc = j - cdi.i0, rc = jc >= 0 && jc < cdi.r.length ? cdi.r[jc] : 0;
      let f = (tN === 1 ? noite : 1 + rc) * (tD === 1 ? dia : 1);
      if (tN !== tD) f *= 1 - custo;
      if (j === e && tD === 1) f *= 1 - custo;
      rp[idx] = f - 1;
      bh[idx] = prep.r[k];
      if (tD === 1) expostos++;
      // operações
      if (tD === 1 && tN === 0) aberta = { entrada: j, fator: dia, pregoes: 1 };
      else if (aberta && tD === 1 && tN === 1) { aberta.fator *= noite * dia; aberta.pregoes++; }
      if (aberta && tD === 0 && tN === 1) {
        aberta.fator *= noite;
        ops.push({ entrada: aberta.entrada, saida: j, ret: aberta.fator * (1 - custo) ** 2 - 1,
                   aberta: false, pregoes: aberta.pregoes });
        aberta = null;
      }
    }
    if (aberta) ops.push({ entrada: aberta.entrada, saida: e, ret: aberta.fator * (1 - custo) ** 2 - 1,
                           aberta: true, pregoes: aberta.pregoes });
    bh[0] = (1 + bh[0]) * (1 - custo) - 1;
    bh[n - 1] = (1 + bh[n - 1]) * (1 - custo) - 1;
    return { s, e, ini: iniT, rp, bh, exposto: expostos / n, ops, alvo: alv };
  }

  function resumoOperacoes(ops) {
    if (!ops.length) return { n: 0, acerto: null, media: null, ganhoMedio: null, perdaMedia: null, duracao: null };
    const rs = ops.map(o => o.ret), g = rs.filter(v => v > 0), pd = rs.filter(v => v <= 0);
    const m = (v) => v.reduce((a, b) => a + b, 0) / v.length;
    return { n: ops.length, acerto: g.length / rs.length, media: m(rs),
             ganhoMedio: g.length ? m(g) : null, perdaMedia: pd.length ? m(pd) : null,
             duracao: m(ops.map(o => o.pregoes)) };
  }

  // =========================================================================
  // Estado na URL
  // =========================================================================
  const NUM = /^-?\d+(\.\d+)?$/;
  function codificar(e) {
    const q = new URLSearchParams();
    if (e.t) q.set('t', e.t);
    if (e.periodo) q.set('p', e.periodo);
    if (e.osc) q.set('i', e.osc);
    if (e.sobre && e.sobre.length) q.set('s', e.sobre.join(','));
    if (e.regra) {
      q.set('r', e.regra);
      const pr = e.params || {};
      const def = REGRAS[e.regra].params;
      const dif = Object.keys(def).filter(k => pr[k] != null && String(pr[k]) !== String(def[k]));
      if (dif.length) q.set('rp', dif.map(k => k + ':' + pr[k]).join(','));
    }
    if (e.de) q.set('de', e.de);
    if (e.filtro && e.filtro !== 'todos') q.set('f', e.filtro);
    return q.toString().replace(/%2C/g, ',').replace(/%3A/g, ':');
  }
  function decodificar(qs) {
    const q = new URLSearchParams(qs), out = {};
    const t = (q.get('t') || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (/^[A-Z0-9]{4}\d{1,2}$/.test(t)) out.t = t;
    if (q.get('p')) out.periodo = q.get('p');
    if (q.get('i')) out.osc = q.get('i');
    if (q.has('s')) out.sobre = q.get('s').split(',').filter(Boolean);
    const r = q.get('r');
    if (r && REGRAS[r]) {
      out.regra = r;
      out.params = { ...REGRAS[r].params };
      for (const par of (q.get('rp') || '').split(',')) {
        const [k, v] = par.split(':');
        if (k in out.params && v != null) out.params[k] = NUM.test(v) ? +v : v;
      }
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(q.get('de') || '')) out.de = q.get('de');
    if (q.get('f')) out.filtro = q.get('f');
    return out;
  }

  const TecMotor = {
    DIAS_ANO, P, JANELAS, CUSTO_BPS, REGRAS,
    lerRetornos, lacunas, trechos, preparar, buscar,
    sma, ema, wilder, ifr, bollinger, macd, estocastico, trueRange, atr, adx, obv,
    maxMovel, minMovel, anterior, calcular, indicadores, resumo,
    alvo, simular, resumoOperacoes, completarCdi, codificar, decodificar,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = TecMotor;
  else raiz.TecMotor = TecMotor;
})(typeof self !== 'undefined' ? self : this);
