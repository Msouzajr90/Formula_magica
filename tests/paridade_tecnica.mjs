/* Roda o motor da aba Análise técnica fora do navegador, para os testes em
 * Python compararem com `tecnica/`. Lê {fn, args} em JSON no stdin e escreve
 * o resultado no stdout. Float64Array vira lista; NaN vira null.
 *
 * fn:
 *   "funcao"  args [nome, ...]  -> TecMotor[nome](...) com listas convertidas
 *   "serie"   args [ret, vel, pregoes]          -> {prep, ind}
 *   "resumo"  args [ret, vel, pregoes, ibov]    -> linha do painel
 *   "simular" args [ret, vel, pregoes, regra, params, cdi, opts] -> backtest
 */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const aqui = dirname(fileURLToPath(import.meta.url));
const M = createRequire(import.meta.url)(join(aqui, '..', 'web', 'public', 'tecnica_motor.js'));

const lista = (v) => Array.from(v, (x) => (Number.isFinite(x) ? x : null));
function plano(o) {
  if (o == null) return o;
  if (ArrayBuffer.isView(o)) return lista(o);
  if (Array.isArray(o)) return o.map(plano);
  if (typeof o === 'object') { const r = {}; for (const k in o) r[k] = plano(o[k]); return r; }
  if (typeof o === 'number' && !Number.isFinite(o)) return null;
  return o;
}
const f64 = (v) => Float64Array.from(v, (x) => (x == null ? NaN : x));
const serieF = (s) => (s ? { i0: s.i0, r: f64(s.r) } : null);

let entrada = '';
process.stdin.on('data', (d) => { entrada += d; });
process.stdin.on('end', () => {
  const { fn, args } = JSON.parse(entrada);
  let out;
  if (fn === 'funcao') {
    const [nome, ...resto] = args;
    out = M[nome](...resto.map((a) => (Array.isArray(a) ? f64(a) : a)));
  } else if (fn === 'serie') {
    const [ret, vel, pregoes] = args;
    const prep = M.preparar(ret, vel, pregoes);
    out = { prep, ind: M.indicadores(prep) };
  } else if (fn === 'resumo') {
    const [ret, vel, pregoes, ibov] = args;
    const prep = M.preparar(ret, vel, pregoes);
    out = M.resumo(prep, M.indicadores(prep), serieF(ibov), pregoes);
  } else if (fn === 'simular') {
    const [ret, vel, pregoes, regra, params, cdi, opts] = args;
    const prep = M.preparar(ret, vel, pregoes);
    const res = M.simular(prep, regra, params, serieF(cdi), opts || {});
    out = res && { ...res, resumoOps: M.resumoOperacoes(res.ops) };
  } else if (fn === 'url') {
    const [estado] = args;
    const qs = M.codificar(estado);
    out = { qs, volta: M.decodificar(qs) };
  } else {
    throw new Error('fn desconhecida: ' + fn);
  }
  process.stdout.write(JSON.stringify(plano(out)));
});
