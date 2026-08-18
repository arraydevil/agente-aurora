"""Indice de recuperacao (a etapa R do RAG).

Implementa BM25 Okapi em Python puro. A escolha e deliberada: para uma base de
poucas centenas de trechos, BM25 entrega qualidade equivalente a de um banco
vetorial sem exigir modelo de embedding, GPU, servico externo ou 400 MB de
dependencia — o que mantem a imagem Docker pequena e o deploy na OCI simples.

Duas adaptacoes ao portugues e ao dominio de beleza:
  1. normalizacao com remocao de acento e de plural simples;
  2. expansao de sinonimos ("gravida" tambem busca "gestacao", "frete" busca
     "entrega"), porque a cliente nunca escreve o termo exato do documento.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from .ingestao import Trecho, carregar_documentos

K1 = 1.5
B = 0.75

PALAVRAS_VAZIAS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "dela", "dele",
    "do", "dos", "e", "ela", "ele", "em", "essa", "esse", "esta", "este", "eu",
    "foi", "isso", "ja", "la", "mais", "mas", "me", "meu", "minha", "muito",
    "na", "nao", "nas", "no", "nos", "o", "os", "ou", "para", "pela", "pelo",
    "por", "posso", "pra", "que", "qual", "quais", "quando", "se", "sem", "ser",
    "seu", "sua", "tem", "ter", "um", "uma", "voce", "vou", "ai", "aqui", "so",
    "eh", "tá", "ta", "oi", "ola", "por favor", "obrigada",
}

# Ponte entre o vocabulario da cliente e o vocabulario do documento.
SINONIMOS: dict[str, list[str]] = {
    "gravida": ["gestacao", "gestante", "gravidez", "liberado", "contraindicado"],
    "gravidez": ["gestacao", "gestante", "liberado", "contraindicado"],
    "gestante": ["gestacao", "gravidez", "liberado", "contraindicado"],
    "amamentando": ["amamentacao", "lactacao", "liberado", "contraindicado"],
    "frete": ["entrega", "envio", "postagem"],
    "entrega": ["frete", "envio", "prazo"],
    "chegar": ["prazo", "entrega"],
    "demora": ["prazo", "entrega"],
    "trocar": ["troca", "devolucao", "reembolso"],
    "devolver": ["devolucao", "troca", "reembolso"],
    "dinheiro": ["reembolso", "estorno"],
    "estorno": ["reembolso"],
    "cancelar": ["cancelamento", "arrependimento", "desistencia"],
    "preco": ["valor", "custa", "custo"],
    "valor": ["preco"],
    "barato": ["preco", "valor"],
    "espinha": ["acne", "acneica", "cravos"],
    "espinhas": ["acne", "acneica"],
    "cravo": ["cravos", "poros", "acne"],
    "mancha": ["manchas", "melasma", "clareador", "pigmentacao"],
    "manchas": ["melasma", "clareador"],
    "ruga": ["rugas", "linhas", "antienvelhecimento", "colageno"],
    "rugas": ["linhas", "antienvelhecimento"],
    "oleosa": ["oleosidade", "sebo", "seborregulador"],
    "seca": ["ressecamento", "hidratacao", "desidratada"],
    "sensivel": ["sensibilidade", "reativa", "calmante"],
    "vermelhidao": ["rosacea", "calmante", "sensivel"],
    "alergia": ["alergeno", "alergica", "reacao", "dermatite"],
    "alergica": ["alergeno", "reacao", "dermatite"],
    "protetor": ["solar", "fps", "filtro"],
    "solar": ["protetor", "fps", "filtro"],
    "sol": ["solar", "fotossensibilizante", "fps"],
    "vegano": ["vegana", "veganos"],
    "animais": ["cruelty", "vegano", "testes"],
    "dados": ["privacidade", "lgpd", "pessoais"],
    "privacidade": ["dados", "lgpd"],
    "senha": ["conta", "cadastro"],
    "rastreio": ["rastreamento", "codigo", "pedido"],
    "sumiu": ["extravio", "sinistro", "rastreio"],
    "perdido": ["extravio", "sinistro"],
    "pontos": ["fidelidade", "lumina"],
    "cupom": ["desconto", "cupons"],
    "nota": ["fiscal", "nf"],
    "clarear": ["clareador", "manchas", "clareamento"],
    "combinar": ["combinacao", "incompatibilidade", "juntos", "misturar"],
    "misturar": ["combinacao", "juntos", "incompatibilidade"],
    "junto": ["combinacao", "juntos", "mesma"],
    "poro": ["poros", "comedogenicidade", "comedogenico"],
    "poros": ["comedogenicidade", "comedogenico"],
    "rotulo": ["inci", "ingredientes", "composicao"],
    "ingrediente": ["inci", "ingredientes"],
    "ingredientes": ["inci", "composicao"],
}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def _radical(palavra: str) -> str:
    """Remocao de plural simples do portugues. Suficiente para BM25."""
    if len(palavra) > 4 and palavra.endswith("es"):
        return palavra[:-2]
    if len(palavra) > 3 and palavra.endswith("s"):
        return palavra[:-1]
    return palavra


def tokenizar(texto: str, expandir: bool = False) -> list[str]:
    bruto = re.findall(r"[a-z0-9]+", normalizar(texto))
    tokens: list[str] = []
    for palavra in bruto:
        if palavra in PALAVRAS_VAZIAS or len(palavra) < 2:
            continue
        tokens.append(_radical(palavra))
        if expandir:
            for sinonimo in SINONIMOS.get(palavra, []):
                tokens.append(_radical(sinonimo))
    return tokens


@dataclass
class Resultado:
    trecho: Trecho
    pontuacao: float


class IndiceBM25:
    def __init__(self, trechos: tuple[Trecho, ...]) -> None:
        self.trechos = trechos
        self.documentos: list[Counter[str]] = []
        self.tamanhos: list[int] = []
        frequencia_documental: Counter[str] = Counter()

        for trecho in trechos:
            tokens = tokenizar(trecho.texto)
            contagem = Counter(tokens)
            self.documentos.append(contagem)
            self.tamanhos.append(len(tokens))
            frequencia_documental.update(contagem.keys())

        self.total = len(trechos)
        self.tamanho_medio = (sum(self.tamanhos) / self.total) if self.total else 0.0
        self.idf: dict[str, float] = {
            termo: math.log(1 + (self.total - df + 0.5) / (df + 0.5))
            for termo, df in frequencia_documental.items()
        }

    def _pontuar(self, indice: int, termos: set[str]) -> tuple[float, int]:
        """Devolve a pontuacao BM25 e quantos termos distintos da consulta bateram."""
        contagem = self.documentos[indice]
        tamanho = self.tamanhos[indice] or 1
        pontuacao = 0.0
        acertos = 0
        for termo in termos:
            frequencia = contagem.get(termo)
            if not frequencia:
                continue
            acertos += 1
            idf = self.idf.get(termo, 0.0)
            numerador = frequencia * (K1 + 1)
            denominador = frequencia + K1 * (1 - B + B * tamanho / (self.tamanho_medio or 1))
            pontuacao += idf * numerador / denominador
        return pontuacao, acertos

    def buscar(
        self,
        consulta: str,
        k: int = 6,
        limite_por_fonte: int | None = 4,
        pontuacao_minima: float = 0.5,
    ) -> list[Resultado]:
        termos = set(tokenizar(consulta, expandir=True))
        if not termos:
            return []

        # Um único termo em comum não caracteriza relevância: a palavra "hoje"
        # aparece por acaso em uma ficha de ingrediente e não torna aquele
        # trecho uma resposta para "qual a escalação do time hoje". Exigir dois
        # termos distintos derruba esse tipo de falso positivo sem prejudicar
        # buscas legítimas de uma palavra só ("niacinamida").
        acertos_minimos = min(2, len(termos))

        brutos: list[Resultado] = []
        for i in range(self.total):
            pontuacao, acertos = self._pontuar(i, termos)
            if acertos >= acertos_minimos and pontuacao >= pontuacao_minima:
                brutos.append(Resultado(self.trechos[i], pontuacao))
        brutos.sort(key=lambda r: r.pontuacao, reverse=True)

        if limite_por_fonte is None:
            return brutos[:k]

        # Diversidade: evita que 6 fichas de ingrediente afoguem a politica de
        # troca quando a pergunta toca os dois assuntos.
        selecionados: list[Resultado] = []
        usados: Counter[str] = Counter()
        for resultado in brutos:
            if usados[resultado.trecho.fonte] >= limite_por_fonte:
                continue
            selecionados.append(resultado)
            usados[resultado.trecho.fonte] += 1
            if len(selecionados) >= k:
                break
        return selecionados


@lru_cache(maxsize=1)
def obter_indice() -> IndiceBM25:
    return IndiceBM25(carregar_documentos())
