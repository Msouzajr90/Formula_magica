/* Executa funções do motor da Simulação fora do navegador, para os testes em
 * Python compararem com magicb3. Lê {fn, args} em JSON no stdin, chama
 * Motor[fn](...args) e escreve o resultado no stdout. Float64Array vira lista.
 *
 * `fn: "otimizar_appjs"` roda o `otimizar` do app.js (a aba de ações), para
 * garantir que a cópia do motor não se afastou do original.
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createContext, runInContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const aqui = dirname(fileURLToPath(import.meta.url));
const publico = join(aqui, '..', 'web', 'public');
const Motor = createRequire(import.meta.url)(join(publico, 'simulacao_motor.js'));

function appjs() {
  const fonte = readFileSync(join(publico, 'app.js'), 'utf8').replace(/\niniciar\(\);\s*$/, '\n');
  const noh = () => new Proxy(function () {}, {
    get: (alvo, prop) => {
      if (prop === 'classList') return { add() {}, remove() {}, toggle() {} };
      if (prop === 'style' || prop === 'dataset') return {};
      if (prop === 'value' || prop === 'textContent' || prop === 'innerHTML') return '';
      if (prop === 'querySelectorAll') return () => [];
      if (prop === Symbol.toPrimitive) return () => '';
      return typeof prop === 'string' ? noh() : undefined;
    },
    apply: () => noh(),
  });
  const ctx = createContext({
    document: { getElementById: () => noh(), querySelectorAll: () => [], querySelector: () => noh(),
                createElementNS: () => noh(), body: {} },
    getComputedStyle: () => ({ getPropertyValue: () => '#000' }),
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {}, innerWidth: 1200, location: { search: '', hash: '' },
    Intl, Math, JSON, Set, Map, Float64Array, Array, Object, console, setTimeout, clearTimeout,
  });
  runInContext(fonte + '\n;globalThis.__otimizar = otimizar;', ctx);
  return ctx.__otimizar;
}

const simples = (v) => JSON.parse(JSON.stringify(v, (k, x) =>
  (x instanceof Float64Array ? Array.from(x) : (typeof x === 'number' && !isFinite(x) ? null : x))));

let entrada = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { entrada += c; });
process.stdin.on('end', () => {
  const { fn, args } = JSON.parse(entrada);
  let r;
  if (fn === 'otimizar_appjs') r = appjs()(...args);
  else r = Motor[fn](...args);
  process.stdout.write(JSON.stringify(simples(r)));
});
