/* Roda o motor da aba Oportunidades fora do navegador, para os testes em
 * Python compararem com `mercado/oportunidades.py`. Lê {fn, args} em JSON no
 * stdin, chama Oport[fn](...args) e escreve o resultado no stdout.
 *
 * `fn: "arquivos"` avalia os JSONs publicados: args = [caminho do
 * pvp_papeis.json, caminho do dados.json, k].
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const aqui = dirname(fileURLToPath(import.meta.url));
const Oport = createRequire(import.meta.url)(join(aqui, '..', 'web', 'public', 'oportunidades_motor.js'));

const entrada = JSON.parse(readFileSync(0, 'utf8'));
let saida;
if (entrada.fn === 'arquivos') {
  const [pp, dados, k] = entrada.args;
  saida = Oport.avaliar(JSON.parse(readFileSync(pp, 'utf8')),
                        dados ? JSON.parse(readFileSync(dados, 'utf8')) : null, k);
} else {
  saida = Oport[entrada.fn](...entrada.args);
}
process.stdout.write(JSON.stringify(saida === undefined ? null : saida));
