/* Motor da aba ETFs — cálculo puro, sem DOM.
 *
 * Lê as mesmas séries da base de preços da Simulação (web/public/precos/) e o
 * catálogo à mão (etfs_catalogo.json). Roda no navegador (como `EtfMotor`) e
 * no Node, onde os testes o comparam com `simulacao/etfs.py`.
 *
 * Convenções
 * ----------
 * - Calendário único `pregoes`. Série `{i0, r}`: `r[k]` é o retorno do pregão
 *   `i0 + k`, do fechamento anterior ao fechamento do dia. A série tem preço
 *   no pregão `i0 − 1` (é dele que sai o primeiro retorno).
 * - Janela que termina em `e` e começa no fechamento `s`: retornos de `s + 1`
 *   a `e`. `s` = último pregão com data ≤ (data de `e` − N meses). O ETF cobre
 *   a janela se `i0 − 1 ≤ s`; senão a célula fica vazia — um "5 anos" calculado
 *   sobre dois anos de história seria outro número com o mesmo rótulo.
 * - Volatilidade, Sharpe e drawdown: retornos DIÁRIOS, as mesmas fórmulas da
 *   Simulação (desvio amostral × √252; Sharpe contra o CDI composto do mesmo
 *   período, anualizado por 252).
 * - Correlação, beta e tracking error: retornos SEMANAIS (blocos de 5 pregões
 *   contados de trás para a frente a partir de `e`). No diário, um ETF de S&P
 *   500 fecha às 17h em São Paulo com Nova York ainda aberta: metade do
 *   movimento de hoje cai amanhã, e a correlação diária sai artificialmente
 *   baixa. Na semana esse descompasso é um dia em cinco.
 *
 * Dois defeitos do Yahoo, tratados aqui e mostrados na tela
 * ----------------------------------------------------------
 * 1. LACUNA: o Yahoo para de atualizar um papel por meses e depois volta. Na
 *    base isso vira uma fila de retornos zero (preço parado) seguida de um
 *    salto que junta tudo o que aconteceu no meio. IMAB11, B5P211 e IRFM11
 *    ficaram parados de mar/2022 a jan/2026 e "subiram" 36% a 53% num pregão.
 *    O salto é verdadeiro — é o retorno de quatro anos —, então NÃO se corta:
 *    o retorno de ponta a ponta continua certo. O que fica sem sentido é tudo
 *    o que depende do caminho (volatilidade, drawdown, correlação) e qualquer
 *    conta que parta de um preço parado. Lacuna = 10 ou mais retornos zero
 *    seguidos, mais o pregão do salto; duas lacunas separadas por até dois
 *    pregões viram uma (o Yahoo às vezes mostra um preço novo e volta ao velho).
 * 2. SALTO ISOLADO fora de lacuna, acima do limite da categoria (15% em renda
 *    fixa, 40% no resto): desdobramento ou grupamento que o Yahoo não ajustou
 *    (SPXI11, 22/01/2026: −87,6% = 1 para 8). Vira retorno zero.
 */
(function (raiz) {
  'use strict';

  const DIAS_ANO = 252;
  const SEMANAS_ANO = 52;
  const BLOCO = 5;                  // pregões por "semana"
  const MIN_SEMANAS = 26;           // correlação/aderência com menos que isso: vazio
  const ATRASO_MAX = 10;            // série que parou há mais pregões que isso: fora
  const LACUNA_MIN = 10;            // retornos zero seguidos que fazem uma lacuna
  const LACUNA_JUNTA = 3;           // lacunas a até 2 pregões uma da outra viram uma
  const JANELAS = { '1m': 1, '3m': 3, '6m': 6, '12m': 12, '3a': 36, '5a': 60, '10a': 120 };
  const ANUALIZA = new Set(['3a', '5a', '10a', 'max']);   // 12m é anual por definição

  const ok = (v) => v != null && Number.isFinite(v);

  // =========================================================================
  // Leitura e preparo
  // =========================================================================
  function lerSerie(arq) {
    const esc = arq.esc || 1e6;
    const r = new Float64Array(arq.r.length);
    for (let k = 0; k < r.length; k++) r[k] = arq.r[k] / esc;
    return { i0: +arq.i0, r, lac: [] };
  }

  const fimDe = (s) => s.i0 + s.r.length - 1;

  /** Série que acaba até ATRASO_MAX pregões antes do fim: completa com zero
   *  (preço parado). Mais atrasada que isso: null — parou de ser negociada. */
  function ateOFim(serie, fim) {
    const falta = fim - fimDe(serie);
    if (falta <= 0) return serie;
    if (falta > ATRASO_MAX) return null;
    const r = new Float64Array(serie.r.length + falta);
    r.set(serie.r);
    return { ...serie, r };
  }

  /** O CDI do último pregão costuma sair só no dia seguinte (SGS): repete a
   *  última taxa diária, que é quase constante. Ibovespa atrasado: zero. */
  function prepararBench(ibov, cdi, fim) {
    let c = cdi;
    const falta = fim - fimDe(cdi);
    if (falta > 0 && falta <= ATRASO_MAX) {
      const r = new Float64Array(cdi.r.length + falta);
      r.set(cdi.r);
      r.fill(cdi.r[cdi.r.length - 1], cdi.r.length);
      c = { ...cdi, r };
    }
    return { ibov: ateOFim(ibov, fim) || ibov, cdi: { ...c, lac: [] } };
  }

  /** Lacunas [a, c] em índices do calendário: a = primeiro pregão parado,
   *  c = pregão do salto que devolve o preço (ou o fim da série, se ainda
   *  parada — `aberta`). Preço parado em a..c−1; retornos inválidos em a..c. */
  function lacunas(serie) {
    const r = serie.r, n = r.length, brutas = [];
    let k = 0;
    while (k < n) {
      if (r[k] !== 0) { k++; continue; }
      let j = k;
      while (j < n && r[j] === 0) j++;
      if (j - k >= LACUNA_MIN) brutas.push([serie.i0 + k, serie.i0 + Math.min(j, n - 1), j >= n]);
      k = j;
    }
    const out = [];
    for (const l of brutas) {
      const u = out[out.length - 1];
      if (u && l[0] - u[1] <= LACUNA_JUNTA) { u[1] = l[1]; u[2] = l[2]; }
      else out.push(l.slice());
    }
    return out;
  }

  /**
   * Série bruta -> série pronta para a conta: completada até o fim, com as
   * lacunas marcadas e os saltos isolados zerados. null se parou de vez
   * (atrasada demais, ou terminando numa lacuna — preço velho no fim).
   */
  function preparar(bruta, limite, pregoes, fim) {
    const cheia = ateOFim(bruta, fim);
    if (!cheia) return { parado: P_(pregoes, fimDe(bruta)) };
    const lac = lacunas(cheia);
    const ult = lac[lac.length - 1];
    if (ult && ult[2]) return { parado: P_(pregoes, ult[0] - 1) };
    const r = Float64Array.from(cheia.r);
    const artefatos = [];
    let li = 0;
    for (let k = 0; k < r.length; k++) {
      const i = cheia.i0 + k;
      while (li < lac.length && lac[li][1] < i) li++;
      if (li < lac.length && lac[li][0] <= i) continue;       // dentro de lacuna
      if (Math.abs(r[k]) > limite) {
        artefatos.push([pregoes[i], Math.round(r[k] * 1e4) / 1e4]);
        r[k] = 0;
      }
    }
    const l2 = lac.map(([a, c]) => [a, c]);
    const s0 = l2.length ? Math.max(cheia.i0 - 1, l2[l2.length - 1][1]) : cheia.i0 - 1;
    return { serie: { i0: cheia.i0, r, lac: l2, s0 }, artefatos };
  }
  const P_ = (pregoes, i) => pregoes[Math.max(0, Math.min(i, pregoes.length - 1))];

  /** O preço de fechamento do pregão i é de verdade (não parado numa lacuna)? */
  const precoReal = (serie, i) => !serie.lac.some(([a, c]) => a <= i && i <= c - 1);
  /** Os retornos s+1..e estão todos fora de lacuna? */
  const limpo = (serie, s, e) => !serie.lac.some(([a, c]) => a <= e && c >= s + 1);

  // =========================================================================
  // Datas e janelas
  // =========================================================================
  const bissexto = (a) => (a % 4 === 0 && a % 100 !== 0) || a % 400 === 0;
  const diasNoMes = (a, m) => [31, bissexto(a) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];

  /** '2026-03-31' − 1 mês = '2026-02-28'. Dia além do fim do mês vira o último. */
  function mesesAntes(data, meses) {
    let [a, m, d] = data.slice(0, 10).split('-').map(Number);
    const t = a * 12 + (m - 1) - meses;
    a = Math.floor(t / 12); m = t - a * 12 + 1;
    d = Math.min(d, diasNoMes(a, m));
    return `${String(a).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
  }

  /** Último índice com pregoes[i] <= data (−1 se nenhum). Busca binária. */
  function ultimoAte(pregoes, data) {
    let lo = 0, hi = pregoes.length - 1, r = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (pregoes[mid] <= data) { r = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return r;
  }

  /** Fechamento de partida da janela que termina em `fim`; null se não cabe.
   *  'ano' = último pregão do ano anterior; 'max' não tem partida comum. */
  function partida(pregoes, fim, janela) {
    if (janela === 'max') return null;
    // 1º de janeiro nunca é pregão: o último pregão até ele é o do ano anterior
    const corte = janela === 'ano' ? `${pregoes[fim].slice(0, 4)}-01-01`
                                   : mesesAntes(pregoes[fim], JANELAS[janela]);
    const s = ultimoAte(pregoes, corte);
    return s < 0 ? null : s;
  }

  /** Partida de uma série numa janela, para RETORNO de ponta a ponta: o preço
   *  da partida tem que existir e ser de verdade. Em 'max', o primeiro preço
   *  depois da última lacuna. */
  function partidaRetorno(serie, s, janela) {
    if (janela === 'max') return serie.s0 ?? serie.i0 - 1;
    if (s == null || serie.i0 - 1 > s || !precoReal(serie, s)) return null;
    return s;
  }

  /** Partida para as contas que dependem do CAMINHO (risco, correlação): além
   *  do preço de partida, nenhum retorno da janela pode cair numa lacuna. */
  function partidaCaminho(serie, s, e, janela) {
    const p = partidaRetorno(serie, s, janela);
    return p != null && limpo(serie, p, e) ? p : null;
  }

  // =========================================================================
  // Contas
  // =========================================================================
  const ret = (serie, i) => serie.r[i - serie.i0];

  function composto(serie, s, e) {
    let v = 1;
    for (let i = s + 1; i <= e; i++) v *= 1 + ret(serie, i);
    return v - 1;
  }

  const anualizar = (total, n) => (n > 0 && total > -1 ? Math.pow(1 + total, DIAS_ANO / n) - 1 : NaN);

  function desvio(a) {
    const n = a.length;
    if (n < 2) return NaN;
    let m = 0; for (const x of a) m += x; m /= n;
    let q = 0; for (const x of a) q += (x - m) ** 2;
    return Math.sqrt(q / (n - 1));
  }

  /** Volatilidade, drawdown máximo e Sharpe dos retornos s+1..e. */
  function risco(serie, cdi, s, e) {
    const n = e - s;
    if (n < 2) return null;
    const r = new Float64Array(n);
    let curva = 1, pico = 1, mdd = 0;
    for (let k = 0; k < n; k++) {
      r[k] = ret(serie, s + 1 + k);
      curva *= 1 + r[k];
      if (curva > pico) pico = curva;
      const dd = curva / pico - 1;
      if (dd < mdd) mdd = dd;
    }
    const total = curva - 1, anual = anualizar(total, n);
    const vol = desvio(r) * Math.sqrt(DIAS_ANO);
    const rf = anualizar(composto(cdi, s, e), n);
    return { total, anual, vol, mdd, sharpe: vol > 0 ? (anual - rf) / vol : NaN, rf, dias: n };
  }

  /** Retornos semanais terminando em e, do mais antigo ao mais novo, só os
   *  blocos inteiros dentro de (s, e]. */
  function semanais(serie, s, e) {
    const nb = Math.floor((e - s) / BLOCO);
    const out = new Float64Array(nb);
    for (let b = 0; b < nb; b++) {
      const fimB = e - (nb - 1 - b) * BLOCO;
      out[b] = composto(serie, fimB - BLOCO, fimB);
    }
    return out;
  }

  function correlacao(x, y) {
    const n = x.length;
    if (n < 2 || y.length !== n) return NaN;
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
    mx /= n; my /= n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      const a = x[i] - mx, b = y[i] - my;
      sxy += a * b; sxx += a * a; syy += b * b;
    }
    return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : NaN;
  }

  function beta(x, y) {   // de x contra y
    const n = x.length;
    if (n < 2) return NaN;
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
    mx /= n; my /= n;
    let sxy = 0, syy = 0;
    for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); syy += (y[i] - my) ** 2; }
    return syy > 0 ? sxy / syy : NaN;
  }

  /** Início comum de duas séries para contas de caminho: o mais tarde entre a
   *  partida da janela e os inícios limpos das duas; null se o trecho até e
   *  tiver lacuna em alguma delas. */
  function inicioComum(x, y, s, e, janela) {
    let a = Math.max(x.s0 ?? x.i0 - 1, y.s0 ?? y.i0 - 1);
    if (janela !== 'max') { if (s == null) return null; a = Math.max(a, s); }
    if (a >= e || !precoReal(x, a) || !precoReal(y, a) || !limpo(x, a, e) || !limpo(y, a, e)) return null;
    return a;
  }

  /** Aderência de x ao ref no período comum dentro da janela. */
  function aderencia(x, ref, s, e, janela) {
    const a = inicioComum(x, ref, s, e, janela);
    if (a == null) return null;
    const wx = semanais(x, a, e), wy = semanais(ref, a, e);
    if (wx.length < MIN_SEMANAS) return null;
    const n = e - a;
    const dif = Array.from(wx, (v, i) => v - wy[i]);
    return {
      desde: a,
      difAnual: anualizar(composto(x, a, e), n) - anualizar(composto(ref, a, e), n),
      te: desvio(dif) * Math.sqrt(SEMANAS_ANO),
      corr: correlacao(wx, wy),
      semanas: wx.length,
      inteira: janela === 'max' || a === s,
    };
  }

  /** Matriz de correlação semanal, par a par no período comum de cada par. */
  function matrizCorrelacao(series, s, e, janela) {
    const p = series.length;
    const M = Array.from({ length: p }, () => new Array(p).fill(null));
    for (let i = 0; i < p; i++) {
      M[i][i] = 1;
      for (let j = i + 1; j < p; j++) {
        const a = inicioComum(series[i], series[j], s, e, janela);
        let c = NaN;
        if (a != null) {
          const wi = semanais(series[i], a, e), wj = semanais(series[j], a, e);
          if (wi.length >= MIN_SEMANAS) c = correlacao(wi, wj);
        }
        M[i][j] = M[j][i] = ok(c) ? c : null;
      }
    }
    return M;
  }

  /** Curva acumulada a partir do fechamento s (valor 0 em s). Dentro de uma
   *  lacuna o preço é velho: null, e a linha retoma no pregão do salto, no
   *  nível certo (o retorno de ponta a ponta não se perde). */
  function curva(serie, s, e) {
    const v = new Array(e - s + 1).fill(null);
    v[0] = 0;
    let acc = 1;
    for (let i = s + 1; i <= e; i++) {
      acc *= 1 + ret(serie, i);
      if (precoReal(serie, i)) v[i - s] = acc - 1;
    }
    return v;
  }

  // =========================================================================
  // A tabela inteira
  // =========================================================================
  const RETORNOS = ['1m', '12m', 'ano', '3a', '5a'];

  /** Limite de salto isolado de um ETF, pela categoria do catálogo. */
  const limiteDe = (catalogo, info) => {
    const lim = catalogo.limiteSalto || {};
    return lim[info.cat] ?? lim.padrao ?? 0.40;
  };

  /** Prepara todas as séries de ETF de uma vez (a tela guarda o resultado). */
  function prepararTodas(dados) {
    const P = dados.indice.pregoes, fim = P.length - 1;
    const prontas = {}, artefatos = {}, parados = [];
    for (const [t, info] of Object.entries(dados.catalogo.etfs)) {
      const bruta = dados.series[t];
      if (!bruta) continue;
      const p = preparar(bruta, limiteDe(dados.catalogo, info), P, fim);
      if (p.parado) { parados.push({ t, ate: p.parado }); continue; }
      prontas[t] = p.serie;
      artefatos[t] = p.artefatos;
    }
    return { prontas, artefatos, parados };
  }

  /**
   * dados = { catalogo, indice (precos/indice.json), series: {t: {i0,r}},
   *           ibov: {i0,r}, cdi: {i0,r} }
   * opts  = { janela: '12m' | '3a' | '5a' | '10a' | 'max' }  (janela do risco
   *           e da aderência)
   * Devolve { fim, linhas, grupos, parados, fora }.
   */
  function avaliar(dados, opts = {}) {
    const janela = opts.janela || '3a';
    const { catalogo, indice } = dados;
    const P = indice.pregoes, fim = P.length - 1;
    const naBase = new Map(indice.ativos.map(a => [a.t, a]));
    const { ibov, cdi } = prepararBench(dados.ibov, dados.cdi, fim);
    const sRisco = partida(P, fim, janela);
    const prep = dados.preparadas || prepararTodas(dados);

    const linhas = [], fora = [];
    for (const [t, info] of Object.entries(catalogo.etfs)) {
      const ent = naBase.get(t), serie = prep.prontas[t];
      if (!ent || !dados.series[t]) { fora.push(t); continue; }
      if (!serie) continue;                                   // parado

      const rets = {};
      for (const j of RETORNOS) {
        const s = partidaRetorno(serie, partida(P, fim, j), j);
        if (s == null) { rets[j] = null; continue; }
        const tot = composto(serie, s, fim);
        rets[j] = ANUALIZA.has(j) ? anualizar(tot, fim - s) : tot;
      }
      const sR = partidaCaminho(serie, sRisco, fim, janela);
      const rk = sR == null ? null : risco(serie, cdi, sR, fim);
      let corrIbov = null, betaIbov = null;
      const a = inicioComum(serie, ibov, sRisco, fim, janela);
      if (a != null && sR != null) {
        const wx = semanais(serie, a, fim), wy = semanais(ibov, a, fim);
        if (wx.length >= MIN_SEMANAS) { corrIbov = correlacao(wx, wy); betaIbov = beta(wx, wy); }
      }
      linhas.push({
        t, nome: info.nome, cat: info.cat, indice: info.indice, grupo: info.grupo || null,
        desde: P[serie.i0 - 1], liq: ent.liq ?? null, neg: ent.neg ?? null,
        ret: rets,
        riscoDesde: sR == null ? null : P[sR],
        anual: rk ? rk.anual : null, vol: rk ? rk.vol : null, mdd: rk ? rk.mdd : null,
        sharpe: rk && ok(rk.sharpe) ? rk.sharpe : null,
        corrIbov: ok(corrIbov) ? corrIbov : null, betaIbov: ok(betaIbov) ? betaIbov : null,
        artefatos: prep.artefatos[t] || [],
        lacunas: serie.lac.map(([x, c]) => [P[x - 1], P[c]]),
      });
    }

    // aderência por grupo
    const grupos = [];
    for (const [g, gi] of Object.entries(catalogo.grupos || {})) {
      const membros = linhas.filter(l => l.grupo === g).map(l => l.t);
      if (!membros.length) continue;
      let ref, refNome, refT = null;
      if (gi.ref === 'IBOV') { ref = ibov; refNome = 'Ibovespa'; }
      else if (gi.ref === 'CDI') { ref = cdi; refNome = 'CDI'; }
      else {
        if (membros.length < 2) continue;
        // o de histórico limpo mais longo; empate, o mais líquido
        const ini = (t) => prep.prontas[t].s0;
        refT = membros.slice().sort((a, b) => ini(a) - ini(b)
          || (naBase.get(b).liq || 0) - (naBase.get(a).liq || 0) || (a < b ? -1 : 1))[0];
        ref = prep.prontas[refT]; refNome = refT;
      }
      const itens = membros.filter(t => t !== refT).map(t => {
        const ad = aderencia(prep.prontas[t], ref, sRisco, fim, janela);
        return { t, ...(ad ? { ...ad, desde: P[ad.desde] } : { vazio: true }) };
      });
      grupos.push({ g, nome: gi.nome, ref: refNome, refT, refNota: gi.refNota || null, itens });
    }
    return { fim: P[fim], janela, inicioRisco: sRisco == null ? null : P[sRisco],
             linhas, grupos, parados: prep.parados, fora };
  }

  // =========================================================================
  // Estado na URL: ?s=BOVA11,IVVB11&j=3a&g=5a&c=acoes_br
  // =========================================================================
  const JANELAS_RISCO = ['12m', '3a', '5a', '10a', 'max'];
  const JANELAS_GRAF = ['12m', '3a', '5a', '10a', 'max'];

  function codificar(e) {
    const p = new URLSearchParams();
    if (e.sel && e.sel.length) p.set('s', e.sel.join(','));
    if (e.janela && e.janela !== '3a') p.set('j', e.janela);
    if (e.grafico && e.grafico !== '5a') p.set('g', e.grafico);
    if (e.cat && e.cat !== 'todas') p.set('c', e.cat);
    return p.toString().replace(/%2C/g, ',');
  }

  function decodificar(qs) {
    const p = new URLSearchParams(qs);
    const sel = (p.get('s') || '').toUpperCase().split(',').map(t => t.replace(/[^A-Z0-9]/g, ''))
      .filter(t => /^[A-Z0-9]{4}11$/.test(t));
    const j = p.get('j'), g = p.get('g');
    return {
      sel: [...new Set(sel)].slice(0, 10),
      janela: JANELAS_RISCO.includes(j) ? j : '3a',
      grafico: JANELAS_GRAF.includes(g) ? g : '5a',
      cat: p.get('c') || 'todas',
    };
  }

  const EtfMotor = {
    DIAS_ANO, BLOCO, MIN_SEMANAS, ATRASO_MAX, LACUNA_MIN, JANELAS, JANELAS_RISCO, JANELAS_GRAF,
    lerSerie, ateOFim, prepararBench, lacunas, preparar, prepararTodas, precoReal, limpo,
    mesesAntes, ultimoAte, partida, partidaRetorno, partidaCaminho, inicioComum,
    composto, anualizar, risco, semanais, correlacao, beta, aderencia,
    matrizCorrelacao, curva, avaliar, codificar, decodificar,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = EtfMotor;
  else raiz.EtfMotor = EtfMotor;
})(typeof self !== 'undefined' ? self : this);
