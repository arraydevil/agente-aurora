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
                "Não consegui gerar a resposta agora. Fale com o atendimento em "
                "atendimento@luminabeauty.com.br ou pelo WhatsApp (11) 4002-8922."
            )
        # O aviso não é decoração. Sem LLM, o que sai daqui é o texto cru dos
        # trechos mais parecidos com a pergunta — e "parecido" inclui o oposto
        # do que a pessoa quer. Perguntar "o que posso usar grávida" recupera
        # justamente as fichas que dizem "contraindicado na gestação". Sem esta
        # ressalva, a lista se parece com uma recomendação.
        return (
            "Não consegui gerar a resposta em linguagem natural agora, então vou "
            "ser honesta: abaixo estão os trechos dos documentos oficiais mais "
            "próximos da sua pergunta, sem nenhuma interpretação minha.\n\n"
            "Leia com atenção antes de decidir qualquer coisa. Esta lista NÃO é "
            "uma recomendação, e pode conter itens que são justamente o contrário "
            "do que você procura.\n\n"
            "Se a sua dúvida envolve gestação, amamentação, alergia ou uso de "
            "medicamento, fale com o atendimento em atendimento@luminabeauty.com.br "
            "ou com sua dermatologista antes de usar qualquer produto.\n\n"
            f"{corpo[:1800]}"
        )


@dataclass
class SaidaLLM:
    texto: str
    provedor: str
    tentativas: list[str]


class Roteador:
    CATALOGO: dict[str, type] = {
        "oci": OciGenAI,
        "groq": Groq,
        "gemini": Gemini,
    }

    def __init__(self, ordem: str | None = None) -> None:
        configurado = ordem or os.getenv("PROVEDORES_LLM", "") or ORDEM_PADRAO
        provedores = self._montar(configurado)

        # Uma variável de ambiente vazia, com um nome errado de provedor ou com
        # espaço sobrando derrubava toda a cascata em silêncio: sobrava apenas o
        # modo extrativo, e a aplicação parecia funcionar. Falhar assim é pior do
        # que falhar barulhento, então voltamos à ordem padrão e registramos.
        if not provedores:
            log.warning(
                "PROVEDORES_LLM=%r não indica nenhum provedor conhecido (%s); "
                "usando a ordem padrão %r",
                configurado, ", ".join(self.CATALOGO), ORDEM_PADRAO,
            )
            provedores = self._montar(ORDEM_PADRAO)

        self.provedores: list[Provedor] = [*provedores, RespostaExtrativa()]

    def _montar(self, lista: str) -> list[Provedor]:
        montados: list[Provedor] = []
        for nome in (n.strip().lower() for n in lista.split(",")):
            classe = self.CATALOGO.get(nome)
            if classe is not None:
                montados.append(classe())
        return montados

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
