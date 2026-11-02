/* Motor da aba Oportunidades: P/VP muito abaixo da própria história.
 *
 * A mesma conta de `mercado/oportunidades.py` (a referência, com a explicação
 * completa). Os testes em Python rodam as duas e comparam
 * (tests/paridade_oportunidades.mjs).
 *
 *   z = (ln P/VP hoje − média do ln P/VP na janela) / desvio do ln na janela
 *
 * Oportunidade: z < −k. Janela de 1, 5 ou 10 anos terminando hoje, incluindo
 * hoje; desvio amostral; cobertura mínima de 80% das semanas.
 */
(function (raiz) {
  'use strict';

  const JANELAS = [1, 5, 10];
  const K_PADRAO = 2;
  const FAIXA_QUASE = 0.5;
  const COBERTURA_MINIMA = 0.8;
  const MINIMO_DE_PONTOS = 26;
  const FATOR_SALTO_VPA = 1.5;
  const FATOR_SALTO = 2;
  const PRAZO_BALANCO_DIAS = 46;

  const ok = (x) => typeof x === 'number' && isFinite(x) && x > 0;
  const iso = (s) => String(s).slice(0, 10);

  /** [ano ISO, semana ISO] de 'AAAA-MM-DD'. */
  function semana(s) {
    const [a, m, d] = iso(s).split('-').map(Number);
    const t = new Date(Date.UTC(a, m - 1, d));
    const dia = t.getUTCDay() || 7;                 // segunda = 1 … domingo = 7
    t.setUTCDate(t.getUTCDate() + 4 - dia);         // quinta da mesma semana
    const ano = t.getUTCFullYear();
    const n = Math.ceil(((t - Date.UTC(ano, 0, 1)) / 86400000 + 1) / 7);
    return [ano, n];
  }

  const mesmaSemana = (a, b) => {
    const x = semana(a), y = semana(b);
    return x[0] === y[0] && x[1] === y[1];
  };

  /** Mesmo dia, N anos antes; 29/02 vira 28/02. */
  function anosAntes(s, anos) {
    const [a, m, d] = iso(s).split('-');
    const md = (m === '02' && d === '29') ? '02-28' : `${m}-${d}`;
    return `${String(+a - anos).padStart(4, '0')}-${md}`;
  }

  const diasEntre = (a, b) => Math.round((Date.parse(iso(b)) - Date.parse(iso(a))) / 86400000);

  /** '2026-10-31 02:08' → '2026-10-30': antes do meio-dia, o dia útil anterior. */
  function dataDoPreco(geradoEm) {
    const g = String(geradoEm || '');
    if (g.length < 10) return null;
    const [a, m, d] = g.slice(0, 10).split('-').map(Number);
    const t = new Date(Date.UTC(a, m - 1, d));
    const hh = g.slice(11, 13);
    const hora = /^\d\d$/.test(hh) ? +hh : 23;
    if (hora < 12) t.setUTCDate(t.getUTCDate() - 1);
    while (t.getUTCDay() === 0 || t.getUTCDay() === 6) t.setUTCDate(t.getUTCDate() - 1);
    return t.toISOString().slice(0, 10);
  }

  /** {datas, valores} com o ponto de hoje: mesma semana substitui, semana nova acrescenta. */
  function comHoje(datas, valores, vpa, preco, dataPreco) {
    datas = datas.slice(); valores = valores.slice();
    if (!(ok(vpa) && ok(preco) && dataPreco)) return { datas, valores };
    dataPreco = iso(dataPreco);
    if (datas.length && dataPreco < datas[datas.length - 1]) return { datas, valores };
    const v = preco / vpa;
    if (datas.length && mesmaSemana(datas[datas.length - 1], dataPreco)) {
      datas[datas.length - 1] = dataPreco; valores[valores.length - 1] = v;
    } else {
      datas.push(dataPreco); valores.push(v);
    }
    return { datas, valores };
  }

  function estatistica(datas, valores, fim, anos) {
    const x = valores[fim];
    if (!ok(x)) return null;
    const corte = anosAntes(datas[fim], anos);
    if (datas[0] > corte && diasEntre(corte, datas[0]) > 7) return null;
    const janela = [];
    let total = 0;
    for (let i = fim; i >= 0 && datas[i] > corte; i--) {
      total++;
      if (ok(valores[i])) janela.push(valores[i]);
    }
    const n = janela.length;
    if (n < MINIMO_DE_PONTOS || n < COBERTURA_MINIMA * total) return null;
    let soma = 0;
    const lns = janela.map(v => Math.log(v));
    for (const l of lns) soma += l;
    const media = soma / n;
    let q = 0;
    for (const l of lns) q += (l - media) * (l - media);
    const dp = Math.sqrt(q / (n - 1));
    if (!(dp > 0)) return null;
    let abaixo = 0;
    for (const v of janela) if (v < x) abaixo++;
    return {
      n, cobertura: n / total, media, dp,
      z: (Math.log(x) - media) / dp,
      percentil: abaixo / n,
      mediaGeo: Math.exp(media),
    };
  }

  /** Maior degrau do patrimônio por ação na janela (degraus = [[índice, VPA], ...]). */
  function saltoVpa(datas, degraus, fim, anos) {
    const corte = anosAntes(datas[fim], anos);
    let melhor = null, anterior = null;
    for (const [i, vpa] of degraus || []) {
      if (i > fim) break;
      if (!ok(vpa)) continue;
      if (anterior != null && datas[i] > corte) {
        const fator = Math.max(vpa / anterior, anterior / vpa);
        if (fator >= FATOR_SALTO_VPA && (!melhor || fator > melhor.fator)) {
          melhor = { tipo: 'patrimonio', data: datas[i], de: anterior, para: vpa, fator };
        }
      }
      anterior = vpa;
    }
    return melhor;
  }

  function somaDias(s, n) {
    const t = new Date(Date.parse(iso(s) + 'T00:00:00Z'));
    t.setUTCDate(t.getUTCDate() + n);
    return t.toISOString().slice(0, 10);
  }

  /** Sem degraus: maior salto semanal do P/VP; depois do prazo do último balanço, é preço e não conta. */
  function saltoPvp(datas, valores, fim, anos, dtBalanco) {
    const corte = anosAntes(datas[fim], anos);
    const soPreco = dtBalanco ? somaDias(dtBalanco, PRAZO_BALANCO_DIAS) : null;
    let melhor = null, posterior = null;
    for (let i = fim; i >= 0 && datas[i] > corte; i--) {
      const v = valores[i];
      if (!ok(v)) continue;
      if (posterior && !(soPreco && datas[posterior.i] > soPreco)) {
        const fator = Math.max(posterior.v / v, v / posterior.v);
        if (fator >= FATOR_SALTO && (!melhor || fator > melhor.fator)) {
          melhor = { tipo: 'pvp', data: datas[posterior.i], de: v, para: posterior.v, fator };
        }
      }
      posterior = { i, v };
    }
    return melhor;
  }

  function maiorSalto(datas, valores, fim, anos, degraus, dtBalanco) {
    return (degraus && degraus.length) ? saltoVpa(datas, degraus, fim, anos)
                                       : saltoPvp(datas, valores, fim, anos, dtBalanco);
  }

  function desde(datas, valores, anos, k) {
    let inicio = null, semanas = 0;
    for (let i = valores.length - 1; i >= 0; i--) {
      const e = estatistica(datas, valores, i, anos);
      if (!e || e.z >= -k) break;
      inicio = datas[i]; semanas++;
    }
    return semanas ? { data: inicio, semanas } : null;
  }

  function avaliarPapel(datas, valores, vpa, preco, dataPreco, k = K_PADRAO, degraus = null, dtBalanco = null) {
    const s = comHoje(datas, valores, vpa, preco, dataPreco);
    const fim = s.valores.length - 1;
    const out = {
      data: s.datas.length ? s.datas[fim] : null,
      pvp: s.valores.length && ok(s.valores[fim]) ? s.valores[fim] : null,
      janelas: {},
    };
    for (const anos of JANELAS) {
      const e = s.valores.length ? estatistica(s.datas, s.valores, fim, anos) : null;
      if (!e) { out.janelas[anos] = null; continue; }
      const gatilho = Math.exp(e.media - k * e.dp);
      out.janelas[anos] = Object.assign(e, {
        gatilho,
        salto: maiorSalto(s.datas, s.valores, fim, anos, degraus, dtBalanco),
        precoGatilho: ok(vpa) ? gatilho * vpa : null,
        desde: e.z < -k ? desde(s.datas, s.valores, anos, k) : null,
      });
    }
    return out;
  }

  function precosDoDia(dados) {
    const precos = {};
    const lista = [...((dados && dados.empresas) || []), ...((dados && dados.excluidas) || [])];
    for (const e of lista) if (e.ticker && ok(e.preco)) precos[String(e.ticker).toUpperCase()] = e.preco;
    const quando = dataDoPreco(((dados && dados.meta) || {}).geradoEm);
    return { precos, quando };
  }

  function avaliar(pp, dados, k = K_PADRAO) {
    const { precos, quando } = precosDoDia(dados);
    const datas = pp.datas || [];
    const res = {};
    for (const [t, info] of Object.entries(pp.papeis || {})) {
      const r = avaliarPapel(datas, info.s || [], info.vpa, precos[t], quando, k, info.v, info.dtBalanco);
      r.nome = info.nome; r.vpa = info.vpa; r.preco = precos[t] ?? null;
      res[t] = r;
    }
    return res;
  }

  function classificar(res, anos, k = K_PADRAO, faixa = FAIXA_QUASE, comSalto = false) {
    const z = (t) => {
      const j = res[t].janelas[anos];
      if (!j || (j.salto && !comSalto)) return null;
      return j.z;
    };
    const com = Object.keys(res).filter(t => z(t) != null);
    const porZ = (a, b) => z(a) - z(b);
    return {
      oportunidades: com.filter(t => z(t) < -k).sort(porZ),
      quase: com.filter(t => z(t) >= -k && z(t) < -k + faixa).sort(porZ),
    };
  }

  const Oport = {
    JANELAS, K_PADRAO, FAIXA_QUASE, COBERTURA_MINIMA, MINIMO_DE_PONTOS, FATOR_SALTO,
    FATOR_SALTO_VPA, PRAZO_BALANCO_DIAS,
    semana, anosAntes, dataDoPreco, comHoje, estatistica, saltoVpa, saltoPvp, maiorSalto, desde, avaliarPapel,
    precosDoDia, avaliar, classificar,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = Oport;
  else raiz.Oport = Oport;
})(typeof self !== 'undefined' ? self : this);
