"""Casar razão social de um cadastro com a de outro.

Existe porque a B3 e a CVM escrevem o nome do mesmo fundo de jeitos diferentes,
e nenhuma das duas publica a chave que ligaria os dois cadastros. A B3 corta a
razão social em cerca de 50 caracteres e abrevia o que sobra; a CVM escreve por
extenso. O mesmo fundo aparece como

    B3   SPARTA INFRA FIC FI INFRA RENDA FIXA CP
    CVM  SPARTA INFRA FI EM COTAS DE FUNDOS INCENTIVADOS DE INVESTIMENTO EM
         INFRAESTRUTURA RENDA FIXA

Três decisões sustentam este módulo, e todas vieram de medição contra os
arquivos reais — 41 FI-Infra e 49 Fiagro listados, contra 33.748 fundos ativos
no cadastro da CVM.

**Comparar palavras, não caracteres.** A semelhança caractere a caractere entre
os dois nomes acima dá 77%, e nenhum corte defensável aceitaria isso. Em
conjunto de palavras eles são quase idênticos. Com abreviação desdobrada
(FDO→FUNDO, INV→INVESTIMENTO, RF→RENDA FIXA, IE→INFRAESTRUTURA) o casamento
sobe de 11 para 27 acertos em 41.

**Pesar cada palavra pelo inverso da frequência.** "INFRAESTRUTURA" aparece em
milhares de fundos e não distingue nada; "SPARTA" aparece em algumas dezenas e
identifica a casa. Sem peso, um fundo chamado só "J&H FIF INVESTIMENTO EM
INFRAESTRUTURA" empata com o candidato certo, porque todas as palavras dele
estão no nome procurado. É o IDF de recuperação de informação, e é o que
separa nome de gestora de vocabulário de prospecto.

**Medir cobertura do nome da B3, não semelhança mútua.** O nome da B3 é, por
construção, o truncado. Exigir que o candidato da CVM não tenha palavras a mais
puniria justamente o nome completo e correto — e premiaria candidatos curtos e
genéricos. A medida principal é: quanto do peso do nome da B3 está no candidato.
A precisão entra só como desempate.

O que este módulo **não** faz é escolher no empate. Quando dois candidatos ficam
a menos de 10 pontos um do outro, ele devolve `None` e a lista de candidatos —
porque um fundo e o FIC que investe nele têm nomes quase iguais e só um deles
tem código na B3. Errar aí publicaria o patrimônio de um sob o código do outro,
que é dado errado com aparência de certo.
"""
from __future__ import annotations

import math
import re
import unicodedata

import pandas as pd

# Cobertura mínima do nome procurado, e vantagem mínima sobre o segundo
# colocado. Medidos: com 0,80 e 0,10, 28 dos 41 FI-Infra casam sozinhos e o
# cruzamento da B3 acha 42 dos 49 Fiagro listados. Nenhum dos casamentos
# automáticos está errado — conferidos um a um contra o cadastro. Os que sobram
# vão para conferência humana.
COBERTURA_MINIMA = 0.80
VANTAGEM_MINIMA = 0.10
CANDIDATOS_MOSTRADOS = 5

# Boilerplate que só é boilerplate em bloco. A remoção é por FRASE, e não por
# palavra, e a diferença é concreta: "CRÉDITO PRIVADO" não distingue fundo
# nenhum, mas "CRÉDITO" sozinho separa o BTG Pactual **Crédito** Agrícola do BTG
# Pactual **Terras** Agrícolas — dois Fiagro listados, com códigos diferentes.
# Jogar "CRÉDITO" fora como palavra solta fazia um virar o outro.
RUIDO_FRASES = (
    r"RESPONSABILIDADE LIMITADA", r"RESP\w* LIMITADA", r"RESP\w* LTDA",
    r"RESP\w* LIM\b", r"\bR LIMITADA\b", r"\bRL\b", r"\bLTDA\b",
    r"CREDITO PRIVADO", r"CRED\w* PRIV\w*", r"CREDITO PRIV\w*",
    r"\bCP\b", r"\bCR PR\b",
    r"RENDA FIXA", r"\bRF\b", r"LONGO PRAZO", r"\bLP\b",
)

# Palavras que aparecem em quase toda razão social de fundo. O IDF já as
# esvaziaria sozinho; tirá-las antes só deixa as contas mais estáveis.
FILLER = {
    "DE", "DA", "DO", "DAS", "DOS", "E", "EM", "A", "O", "AS", "OS", "NO", "NA",
    "NOS", "NAS", "FUNDO", "INVESTIMENTO", "FINANCEIRO",
    "RESPONSABILIDADE", "LIMITADA", "SA", "CLASSE", "UNICA", "CL",
}

# Abreviações da B3 desdobradas para a forma que a CVM usa. Sem isto,
# "FDO INV COTAS" e "FUNDO DE INVESTIMENTO EM COTAS" não têm uma palavra em
# comum.
SINONIMOS = {
    "FDO": "FUNDO", "FDOS": "FUNDO", "FD": "FUNDO", "FUN": "FUNDO",
    "FUND": "FUNDO", "FUNDO": "FUNDO",
    "FUNDOS": "FUNDO", "FUNDS": "FUNDO", "FDS": "FUNDO",
    "INV": "INVESTIMENTO", "INVEST": "INVESTIMENTO", "INVES": "INVESTIMENTO",
    "IN": "INVESTIMENTO", "INVESTIMENTOS": "INVESTIMENTO", "INVS": "INVESTIMENTO",
    "FIN": "FINANCEIRO", "FINAN": "FINANCEIRO", "FINANC": "FINANCEIRO",
    "FINANCEIROS": "FINANCEIRO",
    "CRED": "CREDITO", "PRIV": "PRIVADO",
    "RESP": "RESPONSABILIDADE", "RES": "RESPONSABILIDADE", "LIM": "LIMITADA",
    # FIC, CIC e "em cotas" são a mesma coisa, e é a palavra que separa o fundo
    # do fundo que investe nele — a distinção que mais importa aqui.
    "FIC": "COTA", "FICFI": "COTA", "FIIF": "COTA", "CIC": "COTA",
    "COTAS": "COTA", "CF": "COTA", "FIQ": "COTA",
    "FI": "FUNDO", "FIF": "FUNDO", "FIM": "FUNDO", "FIRF": "FUNDO",
    "INC": "INCENTIVADO", "INCENT": "INCENTIVADO", "INCEN": "INCENTIVADO",
    "INCENTIVADOS": "INCENTIVADO", "INCENTIVADA": "INCENTIVADO",
    "INCENTIVADAS": "INCENTIVADO",
    "IE": "INFRAESTRUTURA", "INFRA": "INFRAESTRUTURA", "INFR": "INFRAESTRUTURA",
    "INF": "INFRAESTRUTURA", "INFRAEST": "INFRAESTRUTURA",
    "INFRAESTR": "INFRAESTRUTURA",
    "DEB": "DEBENTURE", "DEBENTURES": "DEBENTURE",
}

# Fundo master não é listado em bolsa: quem lista é o fundo que investe nele.
# Um candidato marcado como master é descartado quando o nome procurado não diz
# master — e isso não é preciosismo. Medido: o NUIF11 casava com "NU INFRA FUNDO
# INCENTIVADO ... MASTER I" em vez do FIC certo, porque o master compartilhava
# uma palavra a mais com o nome curto da B3. O resultado seria a cota do master
# (R$ 1,55) publicada sob o código de um fundo que negocia a R$ 100.
MARCAS_DE_MASTER = {"MASTER"}

# Palavras que só descrevem a ESTRUTURA do veículo, não o fundo. Se a única
# diferença entre dois candidatos está aqui dentro, eles são o mesmo fundo visto
# de dois lados — o master e o FIC que investe nele — e não dois fundos
# concorrentes. Distinguir os dois casos é o que faz o PREE11 casar sozinho sem
# reabrir a porta para o erro do BIDB11, onde o rival era outra gestora.
ESTRUTURAIS = {"COTA", "MASTER", "II", "III", "IV", "VI", "VII", "VIII", "IX"}


def normalizar(nome) -> str:
    """Maiúsculas, sem acento e sem pontuação. Preserva a ordem das palavras."""
    if nome is None or (isinstance(nome, float) and nome != nome) or pd.isna(nome):
        return ""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", s).upper()).strip()


def tokens(nome) -> set[str]:
    """Palavras significativas, com abreviação desdobrada e plural cortado."""
    texto = normalizar(nome)
    for frase in RUIDO_FRASES:
        texto = re.sub(frase, " ", texto)
    fora = set()
    for bruto in texto.split():
        t = SINONIMOS.get(bruto, bruto)
        if len(t) > 4 and t.endswith("S"):          # COTAS -> COTA
            t = t[:-1]
        t = SINONIMOS.get(t, t)
        if t in FILLER or len(t) < 2:
            continue
        fora.add(t)
    return fora


class Casador:
    """Índice de um cadastro, pronto para receber nomes e devolver candidatos.

    O corpus precisa ter as colunas `CNPJ` e `NOME`; `SITUACAO`, se existir,
    viaja junto no relatório de candidatos. O IDF é calculado sobre este mesmo
    corpus — é ele que define o que é palavra rara.
    """

    def __init__(self, corpus: pd.DataFrame):
        self.corpus = corpus.reset_index(drop=True)
        self.chaves = [tokens(n) for n in self.corpus.get("NOME", [])]
        self.normais = [normalizar(n) for n in self.corpus.get("NOME", [])]
        n = max(len(self.chaves), 1)
        freq: dict[str, int] = {}
        for k in self.chaves:
            for t in k:
                freq[t] = freq.get(t, 0) + 1
        self._peso = {t: math.log(1.0 + n / (df + 1)) for t, df in freq.items()}
        # Peso de uma palavra que não existe no cadastro. A escolha óbvia seria
        # o máximo — palavra raríssima, logo informativa —, e ela está errada
        # aqui: se nenhum candidato tem a palavra, ela não distingue candidato
        # nenhum, só infla o denominador da cobertura. Uma abreviação que a
        # tabela de sinônimos não cobre afundaria sozinha um casamento certo.
        # Foi o que aconteceu com o PREE11: o "FUND" de "SPARTA INFRA
        # ESTRATEGICO FUND DE INVEST" derrubava a nota de 100% para 76%.
        # A mediana trata a desconhecida como uma palavra comum.
        pesos = sorted(self._peso.values())
        self._padrao = pesos[len(pesos) // 2] if pesos else 1.0

    @staticmethod
    def chaves_por_nome(nome: str) -> set[str]:
        return tokens(nome)

    def peso(self, t: str) -> float:
        """Palavra fora do cadastro vale a mediana: não distingue ninguém."""
        return self._peso.get(t, self._padrao)

    def _massa(self, ts) -> float:
        return sum(self.peso(t) for t in ts)

    def _medir(self, alvo: set[str], candidato: set[str]) -> tuple[float, float]:
        """(cobertura do alvo, precisão do candidato), ambas ponderadas."""
        if not alvo or not candidato:
            return 0.0, 0.0
        comum = self._massa(alvo & candidato)
        return comum / self._massa(alvo), comum / self._massa(candidato)

    def candidatos(self, nome: str,
                   n: int = CANDIDATOS_MOSTRADOS) -> pd.DataFrame:
        """Os `n` mais parecidos, do melhor ao pior, com as duas notas.

        `NOTA` é a cobertura do nome procurado e `NOTA2` a precisão do
        candidato. A assimetria é deliberada, e a tentação de usar a maior das
        duas foi testada e descartada: com ela, um candidato genérico cujas
        palavras cabem todas dentro do nome procurado tira nota máxima sem dizer
        nada. Medido, o ROOT11 (Bulletwood) casava com um fundo chamado "RENDA
        FIXA LONGO PRAZO FUNDO DE INVESTIMENTO FINANCEIRO", e o BIDB11 (Inter
        Infra) com um "J&H FIF INVESTIMENTO EM INFRAESTRUTURA". Cobrir o nome
        inteiro é a pergunta certa; caber dentro dele não é.
        """
        colunas = ["CNPJ", "NOME", "SITUACAO", "NOTA", "NOTA2"]
        alvo = tokens(nome)
        if not alvo or self.corpus.empty:
            return pd.DataFrame(columns=colunas)
        medidas = [self._medir(alvo, k) for k in self.chaves]
        out = self.corpus.copy()
        out["NOTA"] = [m[0] for m in medidas]
        out["NOTA2"] = [m[1] for m in medidas]
        existentes = [c for c in colunas if c in out.columns]
        return (out.sort_values(["NOTA", "NOTA2"], ascending=False)
                .head(n)[existentes].reset_index(drop=True))

    def casar(self, nome: str) -> tuple[str | None, float, str]:
        """(CNPJ, cobertura, razão social) — ou (None, ...) quando há dúvida.

        Razão social idêntica é aceita direto: é a evidência mais forte que
        existe, e ela chega a acontecer (o NIKOS é registrado na B3 com o nome
        exato do cadastro). Sem esse atalho, um nome de uma palavra só cairia
        nos cortes por falta de palavras para comparar.
        """
        alvo = tokens(nome)
        if not alvo or self.corpus.empty:
            return None, 0.0, ""

        chave = normalizar(nome)
        iguais = [i for i, n in enumerate(self.normais) if n == chave]
        if len(iguais) == 1:
            i = iguais[0]
            return str(self.corpus.at[i, "CNPJ"]), 1.0, str(self.corpus.at[i, "NOME"])

        tops = self.candidatos(nome, n=4)
        if tops.empty:
            return None, 0.0, ""

        # Fundo master não pode ser escolhido — quem lista em bolsa é o fundo
        # que investe nele —, mas continua competindo. A diferença importa: se o
        # master fosse simplesmente apagado, o segundo colocado herdaria a vaga
        # sem ninguém para disputá-la, e um casamento ruim passaria por falta de
        # concorrência. Foi o que aconteceu com o BIDB11, que assumiu o CNPJ de
        # um "INTER HEDGE" quando o master do "INTER INFRA" saiu da disputa.
        eh_master = [bool(tokens(n) & MARCAS_DE_MASTER) for n in tops["NOME"]]
        alvo_e_master = bool(alvo & MARCAS_DE_MASTER)
        escolhiveis = [i for i in range(len(tops))
                       if alvo_e_master or not eh_master[i]]
        if not escolhiveis:
            return None, float(tops.at[0, "NOTA"]), str(tops.at[0, "NOME"] or "")

        i0 = escolhiveis[0]
        cob = float(tops.at[i0, "NOTA"])
        melhor = str(tops.at[i0, "NOME"] or "")
        if cob < COBERTURA_MINIMA:
            return None, cob, melhor

        # Um master que difere do vencedor só por palavra de estrutura é o
        # master DELE, não um concorrente: bloquear com ele é como perguntar se
        # o fundo é ele mesmo. Um master de outro fundo continua bloqueando.
        vencedor = self.chaves_por_nome(str(tops.at[i0, "NOME"] or ""))
        rivais = [i for i in range(len(tops))
                  if i != i0 and not (
                      eh_master[i]
                      and (vencedor ^ self.chaves_por_nome(str(tops.at[i, "NOME"] or ""))
                           ) <= ESTRUTURAIS)]
        if rivais:
            # Vantagem em qualquer uma das duas medidas basta. Exigir nas duas
            # rejeitaria o caso que a precisão existe para resolver: um fundo e
            # o seu FIC empatam na cobertura por construção.
            #
            # A tolerância não é preciosismo. As duas notas são razões entre
            # somas de poucos pesos, então a folga cai no limite com frequência,
            # e 0,7 − 0,6 dá 0,09999999999999998 em ponto flutuante.
            i1 = rivais[0]
            folga = max(cob - float(tops.at[i1, "NOTA"]),
                        float(tops.at[i0, "NOTA2"]) - float(tops.at[i1, "NOTA2"]))
            if folga < VANTAGEM_MINIMA - 1e-9:
                return None, cob, melhor
        return str(tops.at[i0, "CNPJ"]), cob, melhor
