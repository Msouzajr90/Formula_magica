/* Executa o motor de score do site fora do navegador, para comparar com o do
 * Python. Lê {fundos, pesos, opcoes} em JSON no stdin e escreve o resultado no
 * stdout.
 *
 * `web/public/fiis.js` é um script de página: mexe no DOM já ao ser carregado e
 * chama `iniciar()` no fim. Aqui ele roda num contexto com um DOM de mentira e
 * sem a última linha — o que se quer testar são as funções puras de cálculo,
 * não a renderização.
 */
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const aqui = dirname(fileURLToPath(import.meta.url));
const fonte = readFileSync(join(aqui, '..', 'web', 'public', 'fiis.js'), 'utf8')
  .replace(/\niniciar\(\);\s*$/, '\n');

const noh = () => new Proxy(function () {}, {
  get: (alvo, prop) => {
    if (prop === 'classList') return { add() {}, remove() {}, toggle() {} };
    if (prop === 'style') return {};
    if (prop === 'dataset') return {};
    if (prop === 'value' || prop === 'textContent' || prop === 'innerHTML') return '';
    if (prop === 'querySelectorAll') return () => [];
    if (prop === 'querySelector') return () => noh();
    if (prop === Symbol.toPrimitive) return () => '';
    return typeof prop === 'string' ? noh() : undefined;
  },
  apply: () => noh(),
});

const ctx = createContext({
  document: {
    getElementById: () => noh(),
    querySelectorAll: () => [],
    createElementNS: () => noh(),
    body: {},
  },
  getComputedStyle: () => ({ getPropertyValue: () => '#000' }),
  localStorage: { getItem: () => null, setItem() {} },
  addEventListener() {},
  innerWidth: 1200,
  Intl, Math, JSON, Set, Map, console, setTimeout, clearTimeout,
});
runInContext(fonte, ctx);

let entrada = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { entrada += c; });
process.stdin.on('end', () => {
  const { fundos, pesos, opcoes } = JSON.parse(entrada);
  const r = ctx.calcularScore(fundos, pesos, opcoes || {});
  process.stdout.write(JSON.stringify(r.map(f => ({
    ticker: f.ticker, score: f.score, posicao: f.posicao,
  }))));
});
