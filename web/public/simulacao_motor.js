/* Motor da aba Simulação — cálculo puro, sem DOM.
 *
 * Recebe as séries de retorno da base de preços (web/public/precos/) e a
 * configuração escolhida na tela; devolve a curva da carteira e todas as
 * métricas. Roda no navegador (como `Motor`) e no Node (module.exports), onde
 * os testes o comparam com o Python de `magicb3`.
 *
 * Convenções que atravessam o arquivo inteiro
 * -------------------------------------------
 * - `pregoes[i]` é o calendário único. Uma série `{i0, r}` tem `r[k]` = retorno
 *   do pregão `i0 + k` (fechamento anterior -> fechamento do dia).
 * - A compra é feita no FECHAMENTO do pregão inicial `s`, com o que se sabia
 *   até ali; o primeiro retorno da carteira é o de `s + 1`. Rebalancear é a
 *   mesma coisa no fechamento do primeiro pregão de cada mês/trimestre/ano.
 * - Markowitz só olha para trás: os pesos da data `k` saem dos retornos de
 *   `k - janela + 1` a `k`. Nunca de depois.
 * - Custo: `custoBps` sobre o valor negociado. Compra inicial = 100% do
 *   capital; rebalanceamento = soma de |peso alvo − peso atual|; venda final =
 *   100%. É o mesmo "15 bps por ponta" de `magicb3.backtest`.
 */
(function (raiz) {
  'use strict';

  const DIAS_ANO = 252;

  // =========================================================================
  // Leitura das séries
  // =========================================================================
  /** Arquivo da base ({i0, esc, r: inteiros}) -> {i0, r: Float64Array}. */
  function lerSerie(arq) {
    const esc = arq.esc || 1e6;
    const r = new Float64Array(arq.r.length);
    for (let k = 0; k < r.length; k++) r[k] = arq.r[k] / esc;
    return { i0: arq.i0, r };
  }

  const fimDe = (s) => s.i0 + s.r.length - 1;          // último pregão com retorno
  const ret = (s, i) => s.r[i - s.i0];                  // sem checagem: chame dentro do intervalo

  /** Primeiro pregão >= data (ou o último, se a data passar do fim). */
  function indiceDe(pregoes, data, depois = true) {
    let lo = 0, hi = pregoes.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (pregoes[m] < data) lo = m + 1; else hi = m; }
    if (depois) return Math.min(lo, pregoes.length - 1);
    // último pregão <= data
    if (lo < pregoes.length && pregoes[lo] === data) return lo;
    return Math.max(lo - 1, 0);
  }

  // =========================================================================
  // Markowitz — portado de app.js (que por sua vez é conferido contra
  // magicb3/optimizer.py). A única diferença é o ponto de partida opcional
  // `w0`, que faz as buscas por lambda convergirem em poucas iterações.
  // tests/paridade_simulacao.mjs garante que, sem `w0`, o resultado é
  // idêntico ao do app.js.
  // =========================================================================
  function projetar(v, cap) {
    const n = v.length;
    if (cap * n < 1) cap = 1 / n;
    const soma = (tau) => {
      let s = 0;
      for (let i = 0; i < n; i++) s += Math.min(Math.max(v[i] - tau, 0), cap);
      return s;
    };
    let lo = Math.min(...v) - 1, hi = Math.max(...v);
    for (let k = 0; k < 50; k++) {
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
      let acc = 0; const linha = S[i];
      for (let j = 0; j < n; j++) acc += linha[j] * w[j];
      out[i] = acc;
    }
    return out;
  }
  const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };
  const risco = (S, w) => Math.sqrt(Math.max(dot(w, mulMatVec(S, w)), 0));

  /** Minimiza w'Σw − λ·w'μ com soma 1 e 0 <= w <= cap (gradiente projetado).
   *  Sem `w0`, é exatamente o `otimizar` do app.js. Com `w0`, parte dali e
   *  usa a aceleração de Nesterov (FISTA, com reinício quando o passo piora):
   *  as buscas por λ do máximo Sharpe e da volatilidade-alvo chamam isto
   *  dezenas de vezes por data, e o gradiente simples levava segundos. */
  function otimizar(S, mu, cap, lambda, iteracoes = 900, w0 = null) {
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
    if (!w0) {
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
    let x = projetar(Float64Array.from(w0), cap), y = x, t = 1;
    const z = new Float64Array(n);
    for (let k = 0; k < iteracoes; k++) {
      const Sy = mulMatVec(S, y);
      for (let i = 0; i < n; i++) z[i] = y[i] - passo * (2 * Sy[i] - lambda * mu[i]);
      const xn = projetar(z, cap);
      let dif = 0, subida = 0;
      for (let i = 0; i < n; i++) {
        const d = xn[i] - x[i];
        dif += Math.abs(d);
        subida += (2 * Sy[i] - lambda * mu[i]) * d;
      }
      if (dif < 1e-10) { x = xn; break; }
      const tn = (1 + Math.sqrt(1 + 4 * t * t)) / 2;
      if (subida > 0) { y = xn; t = 1; }                    // reinício adaptativo
      else {
        const yy = new Float64Array(n), f = (t - 1) / tn;
        for (let i = 0; i < n; i++) yy[i] = xn[i] + f * (xn[i] - x[i]);
        y = yy; t = tn;
      }
      x = xn;
    }
    return x;
  }

  /** Covariância com encolhimento de Ledoit-Wolf (alvo: correlação constante), anualizada. */
  function covLedoitWolf(X) {
    const n = X.length, p = X[0].length;
    const media = new Float64Array(p);
    for (const linha of X) for (let j = 0; j < p; j++) media[j] += linha[j] / n;
    const Xc = X.map(l => Array.from(l, (v, j) => v - media[j]));
    const S = Array.from({ length: p }, () => new Float64Array(p));
    for (const l of Xc)
      for (let i = 0; i < p; i++)
        for (let j = i; j < p; j++) { const v = l[i] * l[j] / n; S[i][j] += v; if (i !== j) S[j][i] += v; }
    const varr = new Float64Array(p), std = new Float64Array(p);
    for (let i = 0; i < p; i++) { varr[i] = S[i][i]; std[i] = Math.sqrt(Math.max(varr[i], 0)); }
    let somaR = 0;
    for (let i = 0; i < p; i++)
      for (let j = 0; j < p; j++) { const d = std[i] * std[j]; somaR += d > 0 ? S[i][j] / d : 0; }
    const rBarra = p > 1 ? (somaR - p) / (p * (p - 1)) : 0;
    const F = Array.from({ length: p }, () => new Float64Array(p));
    for (let i = 0; i < p; i++)
      for (let j = 0; j < p; j++) F[i][j] = i === j ? varr[i] : rBarra * std[i] * std[j];
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
    return S.map((linha, i) => Array.from(linha, (v, j) => (delta * F[i][j] + (1 - delta) * v) * DIAS_ANO));
  }

  /** Retorno esperado por média exponencial (λ = 0,97), anualizado. */
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

  /** Zera posições abaixo de 0,5% e renormaliza (mesma regra de magicb3.optimizer.limpar_pesos). */
  function limparPesos(w, minimo = 0.005) {
    let s = 0;
    const out = Array.from(w, v => (v >= minimo ? v : 0));
    for (const v of out) s += v;
    return s > 0 ? out.map(v => v / s) : Array.from(w);
  }

  /** Busca de seção áurea em t = log(λ), maximizando f. Devolve {t, w, v}. */
  function secaoAurea(f, a, b, passos = 22) {
    const g = (Math.sqrt(5) - 1) / 2;
    let c = b - g * (b - a), d = a + g * (b - a);
    let fc = f(c), fd = f(d);
    for (let k = 0; k < passos; k++) {
      if (fc.v > fd.v) { b = d; d = c; fd = fc; c = b - g * (b - a); fc = f(c); }
      else { a = c; c = d; fc = fd; d = a + g * (b - a); fd = f(d); }
    }
    return fc.v > fd.v ? fc : fd;
  }

  /** Pesos de Markowitz para uma janela de retornos X (pregões × ativos).
   *  alvo: 'minvar' | 'maxsharpe' | 'volalvo'. rfAnual é o CDI da janela.
   *  `aviso` é um código (o texto é montado em `simular`, que conta em
   *  quantas datas ele aconteceu em vez de repetir a frase a cada mês). */
  function pesosMarkowitz(X, alvo, opts) {
    const cap = opts.teto, p = X[0].length;
    const S = covLedoitWolf(X), mu = muEwma(X);
    const rf = opts.rfAnual || 0;
    const wMin = otimizar(S, mu, cap, 0, 3000, new Float64Array(p).fill(1 / p));
    const info = { volMin: risco(S, wMin) };
    let w = wMin, aviso = null;

    if (alvo !== 'minvar' && p > 1) {
      const escala = Math.max(...Array.from(mu, Math.abs)) || 1;
      const lo = Math.log(1e-4 / escala), hi = Math.log(1e4 / escala);
      let quente = wMin;
      const resolver = (t) => {
        const wt = otimizar(S, mu, cap, Math.exp(t), 1500, quente);
        quente = wt;
        return wt;
      };
      if (alvo === 'maxsharpe') {
        const sharpe = (wt) => { const v = risco(S, wt); return v > 0 ? (dot(wt, mu) - rf) / v : -Infinity; };
        const melhor = secaoAurea((t) => { const wt = resolver(t); return { t, w: wt, v: sharpe(wt) }; }, lo, hi, 22);
        const cand = sharpe(wMin) >= melhor.v ? wMin : melhor.w;
        if (sharpe(cand) > 0) w = cand;
        else {
          // Com todo Sharpe negativo, "o maior" é o menos negativo, e dividir
          // um excesso negativo por mais risco o aproxima de zero: o máximo
          // apontaria para a carteira MAIS arriscada. Se nada rende acima do
          // CDI na janela, a escolha coerente é a de menor risco.
          w = wMin;
          aviso = 'sharpeNegativo';
        }
      } else if (alvo === 'volalvo') {
        const alvoVol = opts.volAlvo;
        if (alvoVol <= info.volMin + 1e-9) aviso = 'volAbaixo';
        else {
          // a volatilidade cresce com λ: bisseção em log(λ)
          let a = lo, b = hi;
          const wb = resolver(hi);
          if (risco(S, wb) <= alvoVol) { w = wb; aviso = 'volAcima'; }
          else {
            quente = wMin;
            for (let k = 0; k < 28; k++) {
              const m = (a + b) / 2, wm = resolver(m);
              if (risco(S, wm) > alvoVol) b = m; else { a = m; w = wm; }
            }
          }
        }
      }
    }
    w = limparPesos(w);
    info.vol = risco(S, w);
    info.retEsperado = dot(w, mu);
    return { w, aviso, info };
  }

  const TEXTO_AVISO_MK = {
    sharpeNegativo: 'nenhuma combinação dos ativos tinha retorno esperado acima do CDI na janela; nesses casos usei a carteira de mínima variância (com Sharpe negativo, o "máximo" apontaria para a mais arriscada)',
    volAbaixo: 'a volatilidade-alvo ficou abaixo da menor possível com esses ativos; nesses casos usei a carteira de mínima variância',
    volAcima: 'nem a carteira mais concentrada chegou à volatilidade-alvo (o teto por ativo limita o risco); nesses casos usei a de maior retorno esperado',
  };

  // =========================================================================
  // Datas de rebalanceamento
  // =========================================================================
  function chavePeriodo(data, freq) {
    if (freq === 'mensal') return data.slice(0, 7);
    if (freq === 'trimestral') return data.slice(0, 4) + 'T' + Math.floor((+data.slice(5, 7) - 1) / 3);
    if (freq === 'anual') return data.slice(0, 4);
    return null;
  }

  function datasRebalance(pregoes, s, e, freq) {
    const out = [];
    if (!chavePeriodo('2000-01-01', freq)) return out;
    for (let k = s + 1; k < e; k++)
      if (chavePeriodo(pregoes[k], freq) !== chavePeriodo(pregoes[k - 1], freq)) out.push(k);
    return out;
  }

  // =========================================================================
  // Pesos informados
  // =========================================================================
  /** Campo em branco divide o que sobra em partes iguais. Soma diferente de
   *  100% sem campo em branco é normalizada, com aviso. */
  function pesosInformados(ativos) {
    const avisos = [];
    const dados = ativos.map(a => (a.peso == null || a.peso === '' || !isFinite(a.peso)) ? null : Math.max(+a.peso, 0));
    const soma = dados.reduce((x, v) => x + (v ?? 0), 0);
    const brancos = dados.filter(v => v == null).length;
    let w;
    if (brancos === dados.length) w = dados.map(() => 1 / dados.length);
    else if (brancos > 0) {
      const resto = Math.max(1 - soma, 0);
      if (soma > 1 + 1e-9) avisos.push(`os pesos informados somam ${(soma * 100).toFixed(1)}%: os campos em branco ficaram com zero e o total foi normalizado`);
      w = dados.map(v => (v == null ? resto / brancos : v));
      const t = w.reduce((x, v) => x + v, 0);
      w = w.map(v => v / t);
    } else {
      if (Math.abs(soma - 1) > 1e-6) avisos.push(`os pesos somam ${(soma * 100).toFixed(1)}%: normalizei para 100%`);
      w = soma > 0 ? dados.map(v => v / soma) : dados.map(() => 1 / dados.length);
    }
    return { w, avisos };
  }

  // =========================================================================
  // Simulação
  // =========================================================================
  /**
   * dados: { pregoes, series: {T: {i0, r}}, ibov: {i0, r}, cdi: {i0, r} }
   * cfg:   { ativos: [{t, peso}], modo: 'manual'|'markowitz',
   *          alvo: 'minvar'|'maxsharpe'|'volalvo', volAlvo, teto, janela,
   *          rebal: 'nenhum'|'mensal'|'trimestral'|'anual', custoBps, inicio, fim }
   */
  function simular(dados, cfg) {
    const P = dados.pregoes, nP = P.length;
    const avisos = [];
    const nomes = cfg.ativos.map(a => a.t);
    const series = nomes.map(t => dados.series[t]);
    const faltam = nomes.filter((t, i) => !series[i]);
    if (faltam.length) return { erro: `sem dados para ${faltam.join(', ')}` };
    if (!nomes.length) return { erro: 'escolha pelo menos um ativo' };
    const mk = cfg.modo === 'markowitz';
    if (mk && nomes.length < 2) return { erro: 'Markowitz precisa de pelo menos dois ativos' };
    const janela = cfg.janela || DIAS_ANO;
    const custo = (cfg.custoBps ?? 15) / 10000;

    // ---- período efetivo ------------------------------------------------
    // s = pregão da compra (fechamento). Precisa de preço em s (i0-1 <= s) e,
    // no Markowitz, de `janela` retornos até s.
    let sMin = dados.ibov.i0 - 1, eMax = Math.min(fimDe(dados.ibov), nP - 1);
    let quemLimitaIni = null, quemLimitaFim = null;
    series.forEach((s, i) => {
      const precisa = mk ? s.i0 + janela - 1 : s.i0 - 1;
      if (precisa > sMin) { sMin = precisa; quemLimitaIni = nomes[i]; }
      if (fimDe(s) < eMax) { eMax = fimDe(s); quemLimitaFim = nomes[i]; }
    });
    let s = cfg.inicio ? indiceDe(P, cfg.inicio, true) : 0;
    let e = cfg.fim ? indiceDe(P, cfg.fim, false) : nP - 1;
    if (s < sMin) {
      if (quemLimitaIni) {
        avisos.push(mk
          ? `início adiado para ${P[sMin]}: ${quemLimitaIni} só tem 12 meses de histórico (para estimar o Markowitz) a partir daí`
          : `início adiado para ${P[sMin]}: ${quemLimitaIni} só tem cotação a partir daí`);
      }
      s = sMin;
    }
    if (e > eMax) {
      if (quemLimitaFim) avisos.push(`fim antecipado para ${P[eMax]}: é o último pregão com cotação de ${quemLimitaFim}`);
      e = eMax;
    }
    if (e - s < 21) return { erro: `período curto demais (${Math.max(e - s, 0)} pregões entre ${P[s] || '—'} e ${P[e] || '—'}); precisa de pelo menos um mês`, avisos };

    // CDI: o Banco Central publica com um dia de atraso às vezes
    const cdi = dados.cdi;
    const cdiEstimado = new Set();
    const rCdi = (i) => {
      if (i >= cdi.i0 && i <= fimDe(cdi)) return ret(cdi, i);
      if (i > fimDe(cdi)) { cdiEstimado.add(i); return cdi.r[cdi.r.length - 1]; }
      return 0;
    };

    // ---- pesos-alvo em cada data ----------------------------------------
    const nA = nomes.length;
    const informados = mk ? null : pesosInformados(cfg.ativos);
    if (informados) avisos.push(...informados.avisos);
    const avisosMk = new Map();                   // código -> nº de datas
    const alvoEm = (k) => {
      if (!mk) return { w: informados.w };
      const X = [];
      for (let i = k - janela + 1; i <= k; i++) X.push(series.map(sr => ret(sr, i)));
      let rf = 1;
      for (let i = k - janela + 1; i <= k; i++) rf *= 1 + rCdi(i);
      const r = pesosMarkowitz(X, cfg.alvo || 'minvar', {
        teto: cfg.teto ?? 0.15, volAlvo: cfg.volAlvo ?? 0.15,
        rfAnual: Math.pow(rf, DIAS_ANO / janela) - 1,
      });
      if (r.aviso) avisosMk.set(r.aviso, (avisosMk.get(r.aviso) || 0) + 1);
      return r;
    };

    // ---- laço diário ----------------------------------------------------
    const rebs = datasRebalance(P, s, e, cfg.rebal);
    const ehReb = new Set(rebs);
    const n = e - s;                              // nº de retornos da carteira
    const rp = new Float64Array(n), rb = new Float64Array(n), rc = new Float64Array(n);
    const pnl = new Float64Array(nA);
    const somaPesos = new Float64Array(nA);
    const historicoPesos = [];                    // amostrado semanalmente
    const composicoes = [];
    let custos = 0, giro = 0;

    let alvo = alvoEm(s);
    composicoes.push({ data: P[s], w: Array.from(alvo.w), info: alvo.info || null });
    let V = Float64Array.from(alvo.w, v => v * (1 - custo));
    custos += custo;
    giro += 1;
    let total = 1 - custo;
    let anterior = 1;                             // valor no fechamento anterior

    for (let i = s + 1; i <= e; i++) {
      const k = i - s - 1;
      let novo = 0;
      for (let a = 0; a < nA; a++) {
        const x = ret(series[a], i);
        pnl[a] += V[a] * x;
        V[a] *= 1 + x;
        novo += V[a];
      }
      for (let a = 0; a < nA; a++) somaPesos[a] += novo > 0 ? V[a] / novo : 0;
      total = novo;
      if (ehReb.has(i)) {
        alvo = alvoEm(i);
        let mov = 0;
        for (let a = 0; a < nA; a++) mov += Math.abs(alvo.w[a] - V[a] / total);
        const c = custo * mov;
        custos += c * total;
        giro += mov;
        total *= 1 - c;
        for (let a = 0; a < nA; a++) V[a] = alvo.w[a] * total;
        composicoes.push({ data: P[i], w: Array.from(alvo.w), info: alvo.info || null, giro: mov });
      }
      if (i === e) {                              // venda final
        custos += custo * total;
        total *= 1 - custo;
        for (let a = 0; a < nA; a++) V[a] *= 1 - custo;
      }
      rp[k] = total / anterior - 1;
      anterior = total;
      rb[k] = ret(dados.ibov, i);
      rc[k] = rCdi(i);
      if (k % 5 === 0 || i === e) historicoPesos.push({ data: P[i], w: Array.from(V, v => v / total) });
    }
    if (cdiEstimado.size) avisos.push(`CDI dos últimos ${cdiEstimado.size} pregão(ões) ainda não publicado: usei a taxa do último dia`);
    const nDatas = composicoes.length;
    for (const [cod, q] of avisosMk) {
      avisos.push(`Markowitz${nDatas > 1 ? ` (em ${q} de ${nDatas} datas)` : ''}: ${TEXTO_AVISO_MK[cod]}`);
    }

    const datas = P.slice(s + 1, e + 1);
    const metr = metricas(rp, rb, rc, datas);
    const anos = n / DIAS_ANO;

    // ---- por ativo ------------------------------------------------------
    const R = series.map(sr => { const o = new Float64Array(n); for (let i = s + 1; i <= e; i++) o[i - s - 1] = ret(sr, i); return o; });
    const pesoMedio = Array.from(somaPesos, v => v / n);
    const cov = matrizCov(R);
    const sigW = mulMatVec(cov, pesoMedio);
    const varP = dot(pesoMedio, sigW);
    const porAtivo = nomes.map((t, a) => {
      const m = metricas(R[a], rb, rc, datas, { leve: true });
      return {
        t, pesoInicial: composicoes[0].w[a], pesoFinal: V[a] / (total || 1), pesoMedio: pesoMedio[a],
        contribRetorno: pnl[a],                                // em fração do capital inicial
        contribRisco: varP > 0 ? pesoMedio[a] * sigW[a] / varP : NaN,
        anual: m.anual, vol: m.vol, beta: m.beta, mdd: m.mdd, total: m.total,
      };
    });

    return {
      datas, inicio: P[s], fim: P[e], compra: P[s],
      carteira: rp, ibov: rb, cdi: rc,
      metricas: metr,
      metricasIbov: metricas(rb, rb, rc, datas),
      metricasCdi: metricas(rc, rb, rc, datas, { leve: true }),
      porAtivo,
      correlacao: matrizCorr([...R, rb]), rotulosCorrelacao: [...nomes, 'Ibovespa'],
      composicoes, historicoPesos,
      custos, giroAnual: anos > 0 ? (giro - 2) / anos : NaN, nRebalances: composicoes.length - 1,
      avisos,
    };
  }

  // =========================================================================
  // Métricas
  // =========================================================================
  const somaArr = (a) => { let s = 0; for (const x of a) s += x; return s; };
  const anualizar = (total, n) => (n > 0 && total > -1 ? Math.pow(1 + total, DIAS_ANO / n) - 1 : NaN);
  const composto = (a) => { let v = 1; for (const x of a) v *= 1 + x; return v - 1; };

  function desvio(a, media) {
    let s = 0; for (const x of a) s += (x - media) ** 2;
    return a.length > 1 ? Math.sqrt(s / (a.length - 1)) : NaN;
  }

  /** Quantil com interpolação linear (o padrão do numpy). */
  function quantil(a, q) {
    const o = Array.from(a).sort((x, y) => x - y);
    const pos = q * (o.length - 1), lo = Math.floor(pos), hi = Math.ceil(pos);
    return o[lo] + (o[hi] - o[lo]) * (pos - lo);
  }

  function drawdown(rp, datas) {
    const n = rp.length, dd = new Float64Array(n);
    let curva = 1, pico = 1, iPico = -1, mdd = 0, iPicoMdd = -1, iVale = -1;
    let maiorSubmerso = 0, inicioSub = null;
    for (let i = 0; i < n; i++) {
      curva *= 1 + rp[i];
      if (curva >= pico) {
        if (inicioSub !== null) { maiorSubmerso = Math.max(maiorSubmerso, i - inicioSub); inicioSub = null; }
        pico = curva; iPico = i;
      } else if (inicioSub === null) inicioSub = iPico + 1;
      dd[i] = curva / pico - 1;
      if (dd[i] < mdd) { mdd = dd[i]; iVale = i; iPicoMdd = iPico; }
    }
    if (inicioSub !== null) maiorSubmerso = Math.max(maiorSubmerso, n - inicioSub);
    // recuperação: primeiro dia depois do vale em que a curva volta ao pico
    let iRec = -1;
    if (iVale >= 0) {
      for (let i = iVale + 1; i < n; i++) if (dd[i] >= -1e-12) { iRec = i; break; }
    }
    const data = (i) => (i < 0 ? (datas.inicio || null) : datas[i]);
    return {
      serie: dd, mdd,
      pico: iVale >= 0 ? data(iPicoMdd) : null,
      vale: iVale >= 0 ? datas[iVale] : null,
      recuperacao: iRec >= 0 ? datas[iRec] : null,
      pregoesQueda: iVale >= 0 ? iVale - iPicoMdd : 0,
      pregoesRecuperacao: iRec >= 0 ? iRec - iVale : null,
      maiorSubmerso,
    };
  }

  /** Retornos compostos por mês do calendário: [{mes:'AAAA-MM', v}]. */
  function mensais(r, datas) {
    const out = [];
    let mes = null, acc = 1;
    for (let i = 0; i < r.length; i++) {
      const m = datas[i].slice(0, 7);
      if (m !== mes) { if (mes) out.push({ mes, v: acc - 1 }); mes = m; acc = 1; }
      acc *= 1 + r[i];
    }
    if (mes) out.push({ mes, v: acc - 1 });
    return out;
  }

  function captura(mp, mb, sinal) {
    const p = [], b = [];
    for (let i = 0; i < mb.length; i++) if (sinal > 0 ? mb[i].v > 0 : mb[i].v < 0) { p.push(mp[i].v); b.push(mb[i].v); }
    if (!b.length) return NaN;
    const gp = Math.pow(1 + composto(p), 1 / p.length) - 1, gb = Math.pow(1 + composto(b), 1 / b.length) - 1;
    return gb !== 0 ? gp / gb : NaN;
  }

  /** Janela móvel de 252 pregões: retorno composto e volatilidade anualizada. */
  function moveis(r, janela = DIAS_ANO) {
    const n = r.length, ret12 = new Array(n).fill(null), vol12 = new Array(n).fill(null);
    if (n < janela) return { ret12, vol12 };
    let logAcc = 0, s1 = 0, s2 = 0;
    for (let i = 0; i < n; i++) {
      const lg = Math.log1p(r[i]);
      logAcc += lg; s1 += r[i]; s2 += r[i] * r[i];
      if (i >= janela) { const o = r[i - janela]; logAcc -= Math.log1p(o); s1 -= o; s2 -= o * o; }
      if (i >= janela - 1) {
        ret12[i] = Math.exp(logAcc) - 1;
        const media = s1 / janela;
        vol12[i] = Math.sqrt(Math.max((s2 - janela * media * media) / (janela - 1), 0) * DIAS_ANO);
      }
    }
    return { ret12, vol12 };
  }

  /**
   * Métricas de uma série diária `rp` contra o Ibovespa `rb` e o CDI `rc`.
   * Sharpe e Sortino usam o CDI composto do MESMO período como taxa livre de
   * risco; alfa e beta seguem magicb3.backtest.calcular_metricas, com rf_aa =
   * esse CDI anualizado.
   */
  function metricas(rp, rb, rc, datas, opts = {}) {
    const n = rp.length;
    if (!n) return {};
    const total = composto(rp), anual = anualizar(total, n);
    const media = somaArr(rp) / n;
    const vol = desvio(rp, media) * Math.sqrt(DIAS_ANO);
    const totalCdi = composto(rc), rf = anualizar(totalCdi, n);
    const dd = drawdown(rp, datas);

    let cov = 0, varb = 0;
    const mb = somaArr(rb) / n;
    for (let i = 0; i < n; i++) { cov += (rp[i] - media) * (rb[i] - mb); varb += (rb[i] - mb) ** 2; }
    const beta = varb > 0 ? cov / varb : NaN;
    const totalB = composto(rb), anualB = anualizar(totalB, n);
    const base = { total, anual, vol, sharpe: vol > 0 ? (anual - rf) / vol : NaN, mdd: dd.mdd, beta, dias: n };
    if (opts.leve) return base;

    const alfa = anual - (rf + beta * (anualB - rf));
    const ativo = Array.from(rp, (x, i) => x - rb[i]);
    const ma = somaArr(ativo) / n;
    const te = desvio(ativo, ma) * Math.sqrt(DIAS_ANO);
    let sq = 0;
    for (let i = 0; i < n; i++) { const x = Math.min(rp[i] - rc[i], 0); sq += x * x; }
    const dsv = Math.sqrt(sq / n * DIAS_ANO);

    const mp = mensais(rp, datas), mbm = mensais(rb, datas), mc = mensais(rc, datas);
    const q95 = quantil(rp, 0.05), q99 = quantil(rp, 0.01);
    const cauda = (q) => { const c = Array.from(rp).filter(x => x <= q); return c.length ? -somaArr(c) / c.length : NaN; };
    const positivos = mp.filter(m => m.v > 0).length;
    const ordenados = mp.slice().sort((a, b) => a.v - b.v);

    return {
      ...base,
      sortino: dsv > 0 ? (anual - rf) / dsv : NaN,
      rf, totalCdi, totalB, anualB,
      alfa, te, ir: te > 0 ? (ma * DIAS_ANO) / te : NaN,
      correlacaoIbov: varb > 0 ? cov / Math.sqrt(varb * desvio(rp, media) ** 2 * (n - 1)) : NaN,
      capturaAlta: captura(mp, mbm, 1), capturaBaixa: captura(mp, mbm, -1),
      var95: -q95, cvar95: cauda(q95), var99: -q99, cvar99: cauda(q99),
      drawdown: dd,
      mensal: mp, mensalIbov: mbm, mensalCdi: mc,
      mesesPositivos: mp.length ? positivos / mp.length : NaN,
      melhorMes: ordenados[ordenados.length - 1] || null, piorMes: ordenados[0] || null,
      moveis: moveis(rp), moveisIbov: moveis(rb),
    };
  }

  function matrizCov(R) {
    const p = R.length, n = R[0] ? R[0].length : 0;
    const medias = R.map(r => somaArr(r) / n);
    const C = Array.from({ length: p }, () => new Float64Array(p));
    for (let i = 0; i < p; i++)
      for (let j = i; j < p; j++) {
        let s = 0;
        for (let k = 0; k < n; k++) s += (R[i][k] - medias[i]) * (R[j][k] - medias[j]);
        C[i][j] = C[j][i] = n > 1 ? s / (n - 1) * DIAS_ANO : NaN;
      }
    return C;
  }

  function matrizCorr(R) {
    const C = matrizCov(R);
    return C.map((l, i) => Array.from(l, (v, j) => {
      const d = Math.sqrt(C[i][i] * C[j][j]);
      return d > 0 ? v / d : (i === j ? 1 : NaN);
    }));
  }

  // =========================================================================
  // Estado na URL
  // =========================================================================
  const REB = { nenhum: 'n', mensal: 'm', trimestral: 't', anual: 'a' };
  const REB_INV = Object.fromEntries(Object.entries(REB).map(([k, v]) => [v, k]));

  /** cfg -> "a=PETR4:30,VALE3:20,ITUB4&m=mk&o=vol15&t=15&r=t&c=15&de=…&ate=…" */
  function codificar(cfg) {
    const p = new URLSearchParams();
    p.set('a', cfg.ativos.map(a => a.t + (a.peso != null && a.peso !== '' && isFinite(a.peso)
      ? ':' + +(a.peso * 100).toFixed(2) : '')).join(','));
    p.set('m', cfg.modo === 'markowitz' ? 'mk' : 'man');
    if (cfg.modo === 'markowitz') {
      p.set('o', cfg.alvo === 'volalvo' ? 'vol' + +((cfg.volAlvo ?? 0.15) * 100).toFixed(1)
        : cfg.alvo === 'maxsharpe' ? 'sharpe' : 'minvar');
      p.set('t', String(+((cfg.teto ?? 0.15) * 100).toFixed(1)));
    }
    p.set('r', REB[cfg.rebal] || 'n');
    p.set('c', String(cfg.custoBps ?? 15));
    if (cfg.inicio) p.set('de', cfg.inicio);
    if (cfg.fim) p.set('ate', cfg.fim);
    return p.toString().replace(/%3A/g, ':').replace(/%2C/g, ',');
  }

  /** Inverso de `codificar`. Campo inválido volta ao padrão, nunca quebra. */
  function decodificarEstado(qs) {
    const p = new URLSearchParams(qs);
    const ativos = (p.get('a') || '').split(',').map(x => x.trim()).filter(Boolean).map(x => {
      const [t, w] = x.split(':');
      const v = w != null && w !== '' && isFinite(+w) ? +w / 100 : null;
      return { t: t.toUpperCase().replace(/[^A-Z0-9]/g, ''), peso: v };
    }).filter(a => /^[A-Z0-9][A-Z0-9]{3}\d{1,2}$/.test(a.t));
    const o = p.get('o') || 'minvar';
    const num = (k, d, lo, hi) => { const v = +p.get(k); return p.has(k) && isFinite(v) && v >= lo && v <= hi ? v : d; };
    const data = (k) => (/^\d{4}-\d{2}-\d{2}$/.test(p.get(k) || '') ? p.get(k) : null);
    return {
      ativos,
      modo: p.get('m') === 'mk' ? 'markowitz' : 'manual',
      alvo: o.startsWith('vol') ? 'volalvo' : (o === 'sharpe' ? 'maxsharpe' : 'minvar'),
      volAlvo: o.startsWith('vol') && isFinite(+o.slice(3)) && +o.slice(3) > 0 ? +o.slice(3) / 100 : 0.15,
      teto: num('t', 15, 1, 100) / 100,
      rebal: REB_INV[p.get('r')] || 'nenhum',
      custoBps: num('c', 15, 0, 500),
      inicio: data('de'), fim: data('ate'),
    };
  }

  const Motor = {
    DIAS_ANO, lerSerie, simular, metricas, pesosMarkowitz, pesosInformados,
    datasRebalance, drawdown, mensais, moveis, quantil, otimizar, projetar,
    covLedoitWolf, muEwma, limparPesos, matrizCorr, indiceDe,
    codificar, decodificarEstado,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = Motor;
  else raiz.Motor = Motor;
})(typeof self !== 'undefined' ? self : this);
