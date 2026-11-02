/* Roda o motor da aba ETFs fora do navegador, para os testes em Python
 * compararem com `simulacao/etfs.py`. Lê {fn, args} em JSON no stdin.
 *
 * fn "pasta":  args = [pasta de preços, catálogo, janela] — carrega como a tela.
 * fn "dados":  args = [arquivo com {catalogo, indice, series, ibov, cdi}, janela]
 *              (séries no formato dos arquivos da base: {i0, esc, r}).
 * fn "extras": args = [arquivo de dados, janela, tickers] — matriz de
 *              correlação e curvas, que a tela calcula fora do `avaliar`.
 * Qualquer outro fn chama EtfMotor[fn](...args).
 */
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const aqui = dirname(fileURLToPath(import.meta.url));
const M = createRequire(import.meta.url)(join(aqui, '..', 'web', 'public', 'etfs_motor.js'));
const ler = (p) => JSON.parse(readFileSync(p, 'utf8'));

function deArquivo(d) {
  const series = {};
  for (const [t, a] of Object.entries(d.series)) series[t] = M.lerSerie(a);
  return { catalogo: d.catalogo, indice: d.indice, series, ibov: M.lerSerie(d.ibov), cdi: M.lerSerie(d.cdi) };
}

function daPasta(pasta, catalogo) {
  const indice = ler(join(pasta, 'indice.json'));
  const cat = ler(catalogo);
  const series = {};
  for (const a of indice.ativos) {
    const arq = join(pasta, a.t + '.json');
    if (cat.etfs[a.t] && existsSync(arq)) series[a.t] = M.lerSerie(ler(arq));
  }
  return { catalogo: cat, indice, series,
           ibov: M.lerSerie(ler(join(pasta, indice.bench.IBOV.arquivo))),
           cdi: M.lerSerie(ler(join(pasta, indice.bench.CDI.arquivo))) };
}

const entrada = JSON.parse(readFileSync(0, 'utf8'));
const [a0, a1, a2] = entrada.args;
let saida;
if (entrada.fn === 'pasta') saida = M.avaliar(daPasta(a0, a1), { janela: a2 });
else if (entrada.fn === 'dados') saida = M.avaliar(deArquivo(ler(a0)), { janela: a1 });
else if (entrada.fn === 'extras') {
  const d = deArquivo(ler(a0));
  const P = d.indice.pregoes, fim = P.length - 1;
  const prep = M.prepararTodas(d);
  const { ibov } = M.prepararBench(d.ibov, d.cdi, fim);
  const ts = a2.filter(t => prep.prontas[t]);
  const s = M.partida(P, fim, a1);
  const series = [...ts.map(t => prep.prontas[t]), ibov];
  const curvas = {};
  for (const t of ts) {
    const s0 = a1 === 'max' ? prep.prontas[t].i0 - 1 : s;
    curvas[t] = s0 != null && s0 >= prep.prontas[t].i0 - 1 ? M.curva(prep.prontas[t], s0, fim) : null;
  }
  saida = { tickers: ts, matriz: M.matrizCorrelacao(series, s, fim, a1), curvas };
} else saida = M[entrada.fn](...entrada.args);

process.stdout.write(JSON.stringify(saida === undefined ? null : saida, (k, v) =>
  (typeof v === 'number' && !Number.isFinite(v) ? null : v)));
