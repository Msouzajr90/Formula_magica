/* Roda a simulação fora da linha principal: um Markowitz mensal com trinta
 * ativos leva alguns segundos, e a tela não pode congelar enquanto isso. */
'use strict';
importScripts('simulacao_motor.js');
self.onmessage = (ev) => {
  const { id, dados, cfg } = ev.data;
  let res;
  try { res = self.Motor.simular(dados, cfg); }
  catch (e) { res = { erro: 'falha no cálculo: ' + (e && e.message || e) }; }
  self.postMessage({ id, res });
};
