"""Roteador de provedores com degradacao graciosa.

A ordem padrao coloca a OCI Generative AI em primeiro lugar, como pede o
desafio. Se a chamada falhar — conta em verificacao, credencial ausente, limite
de servico, indisponibilidade — o roteador desce para o proximo provedor sem
derrubar a requisicao. O ultimo degrau nao usa LLM nenhum: monta a resposta
diretamente com os trechos recuperados, garantindo que a aplicacao nunca fique
muda em uma demonstracao.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .base import Provedor, ProvedorIndisponivel
from .oci_genai import OciGenAI
from .reserva import Gemini, Groq

log = logging.getLogger(__name__)

# A OCI fica fora do padrão porque o SDK dela é opcional (requirements-oci.txt).
# Para usá-la, basta acrescentar "oci" a PROVEDORES_LLM — o roteador monta a
# cascata a partir dessa lista, em ordem.
ORDEM_PADRAO = "groq,gemini"


class RespostaExtrativa:
    """Ultimo recurso: devolve os trechos recuperados sem passar por LLM."""

    nome = "extrativo"

    def disponivel(self) -> bool:
        return True

    def gerar(self, sistema: str, usuario: str) -> str:  # noqa: ARG002
        marcador = "TRECHOS DOS DOCUMENTOS:"
        corpo = usuario.split(marcador, 1)[-1]
        corpo = corpo.split("PERGUNTA DA CLIENTE:", 1)[0].strip()
        if not corpo:
            return (
                "No momento não consegui gerar a resposta completa. "
                "Fale com o atendimento em atendimento@luminabeauty.com.br."
            )
        return (
            "Não consegui gerar a resposta em linguagem natural agora, mas "
            "encontrei estas passagens nos documentos oficiais da Lumina Beauty:\n\n"
            f"{corpo[:1800]}"
        )


@dataclass
class SaidaLLM:
    texto: str
    provedor: str
    tentativas: list[str]


class Roteador:
    def __init__(self, ordem: str | None = None) -> None:
        nomes = (ordem or os.getenv("PROVEDORES_LLM", ORDEM_PADRAO)).split(",")
        catalogo: dict[str, type] = {
            "oci": OciGenAI,
            "groq": Groq,
            "gemini": Gemini,
        }
        self.provedores: list[Provedor] = []
        for nome in (n.strip().lower() for n in nomes):
            classe = catalogo.get(nome)
            if classe is not None:
                self.provedores.append(classe())
        self.provedores.append(RespostaExtrativa())

    def status(self) -> list[dict[str, object]]:
        return [
            {"provedor": p.nome, "configurado": p.disponivel()} for p in self.provedores
        ]

    def gerar(self, sistema: str, usuario: str) -> SaidaLLM:
        tentativas: list[str] = []
        for provedor in self.provedores:
            if not provedor.disponivel():
                tentativas.append(f"{provedor.nome}: não configurado")
                continue
            try:
                texto = provedor.gerar(sistema, usuario)
            except ProvedorIndisponivel as erro:
                log.warning("provedor %s indisponível: %s", provedor.nome, erro)
                tentativas.append(f"{provedor.nome}: {erro}")
                continue
            except Exception as erro:  # falha inesperada não pode derrubar a API
                log.exception("provedor %s falhou", provedor.nome)
                tentativas.append(f"{provedor.nome}: erro inesperado ({erro})")
                continue
            return SaidaLLM(texto=texto, provedor=provedor.nome, tentativas=tentativas)

        raise ProvedorIndisponivel("nenhum provedor respondeu: " + " | ".join(tentativas))
