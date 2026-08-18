"""Aurora — agente de atendimento da Lumina Beauty.

Fluxo de uma pergunta:

    pergunta -> BM25 sobre os documentos -> trechos + citacao
             -> prompt ancorado -> LLM (OCI, com fallback) -> resposta + fontes

O ponto central e que o LLM nunca responde de memoria: ele so pode usar o que o
indice recuperou dos documentos. Isso e o que separa um agente com base de
conhecimento de um chatbot generico.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .indice import IndiceBM25, Resultado, obter_indice
from .llm import ProvedorIndisponivel, Roteador

log = logging.getLogger(__name__)

PROMPT_SISTEMA = """Você é a Aurora, atendente virtual da Lumina Beauty, um e-commerce brasileiro de dermocosméticos.

COMO VOCÊ RESPONDE
- Português do Brasil, tom acolhedor e direto. Trate a pessoa por "você".
- Seja objetiva: 2 a 5 parágrafos curtos, ou uma lista quando houver itens.
- Comece pela resposta. Contexto vem depois, se for necessário.

REGRA MAIS IMPORTANTE
Responda EXCLUSIVAMENTE com base nos trechos de documento fornecidos abaixo.
- Nunca invente preço, prazo, código de produto, e-mail ou política.
- Se a informação não estiver nos trechos, diga com franqueza que não encontrou
  essa informação nos documentos e ofereça o contato do atendimento humano
  (atendimento@luminabeauty.com.br ou WhatsApp (11) 4002-8922).
- Não complete lacunas com conhecimento geral sobre cosméticos.

CITAÇÃO DE FONTES
Ao final da resposta, liste as fontes que você realmente usou, no formato:
Fontes: [nome_do_arquivo — referência]
Se não usou nenhum trecho, não invente fonte.

RECOMENDAÇÃO DE PRODUTO
- Cite nome, código e preço exatamente como aparecem no trecho.
- Confira se o tipo de pele bate com o que a pessoa descreveu.
- Se o produto estiver esgotado, avise.
- No máximo 3 produtos por resposta.

SEGURANÇA E LIMITES
- Você não é médica. Não diagnostique, não prescreva, não indique medicamento.
- Se a pessoa mencionar gestação, amamentação, condição de pele diagnosticada,
  uso de medicação ou reação adversa, oriente pelo documento E recomende
  avaliação com dermatologista.
- Se os trechos indicarem incompatibilidade entre ativos, avise sempre, mesmo
  que a pessoa não tenha perguntado sobre isso.
- Se um ingrediente for de uso restrito ou proibido, deixe isso explícito."""


@dataclass
class Fonte:
    documento: str
    referencia: str
    pontuacao: float
    tipo: str

    def como_dicionario(self) -> dict[str, Any]:
        return {
            "documento": self.documento,
            "referencia": self.referencia,
            "pontuacao": round(self.pontuacao, 3),
            "tipo": self.tipo,
        }


@dataclass
class RespostaAgente:
    resposta: str
    fontes: list[Fonte] = field(default_factory=list)
    provedor: str = "indisponivel"
    trechos_recuperados: int = 0
    tempo_ms: int = 0
    tentativas: list[str] = field(default_factory=list)

    def como_dicionario(self) -> dict[str, Any]:
        return {
            "resposta": self.resposta,
            "fontes": [f.como_dicionario() for f in self.fontes],
            "provedor": self.provedor,
            "trechos_recuperados": self.trechos_recuperados,
            "tempo_ms": self.tempo_ms,
            "tentativas": self.tentativas,
        }


MENSAGEM_SEM_CONTEXTO = (
    "Não encontrei essa informação nos documentos da Lumina Beauty. "
    "Consigo ajudar com produtos do catálogo, ingredientes, prazos de entrega, "
    "trocas e devoluções, privacidade e combinação de ativos.\n\n"
    "Se for algo fora disso, o time humano resolve rapidinho: "
    "atendimento@luminabeauty.com.br ou WhatsApp (11) 4002-8922."
)


class AgenteAurora:
    def __init__(
        self,
        indice: IndiceBM25 | None = None,
        roteador: Roteador | None = None,
        k: int = 6,
    ) -> None:
        self.indice = indice or obter_indice()
        self.roteador = roteador or Roteador()
        self.k = k

    # ------------------------------------------------------------- contexto

    @staticmethod
    def _montar_contexto(resultados: list[Resultado]) -> str:
        blocos = []
        for posicao, resultado in enumerate(resultados, start=1):
            trecho = resultado.trecho
            blocos.append(
                f"[{posicao}] Fonte: {trecho.fonte} — {trecho.referencia} "
                f"(relevância {resultado.pontuacao:.2f})\n{trecho.texto}"
            )
        return "\n\n---\n\n".join(blocos)

    @staticmethod
    def _montar_historico(historico: list[dict[str, str]] | None) -> str:
        if not historico:
            return ""
        linhas = []
        for turno in historico[-4:]:  # janela curta: só o fio da conversa atual
            papel = "Cliente" if turno.get("papel") == "cliente" else "Aurora"
            texto = (turno.get("texto") or "").strip()
            if texto:
                linhas.append(f"{papel}: {texto}")
        if not linhas:
            return ""
        return "CONVERSA ATÉ AQUI (use apenas para entender o contexto):\n" + "\n".join(linhas) + "\n\n"

    # -------------------------------------------------------------- resposta

    def responder(
        self, pergunta: str, historico: list[dict[str, str]] | None = None
    ) -> RespostaAgente:
        inicio = time.perf_counter()
        pergunta = (pergunta or "").strip()

        if not pergunta:
            return RespostaAgente(
                resposta="Me conta o que você precisa que eu te ajudo. 💜",
                tempo_ms=int((time.perf_counter() - inicio) * 1000),
            )

        # Em pergunta de acompanhamento ("e ele serve pra pele oleosa?"), o texto
        # sozinho recupera mal. Somamos o último turno da cliente à consulta.
        consulta = pergunta
        if historico:
            ultimas = [
                t.get("texto", "")
                for t in historico[-2:]
                if t.get("papel") == "cliente"
            ]
            if ultimas and len(pergunta.split()) <= 8:
                consulta = f"{ultimas[-1]} {pergunta}"

        resultados = self.indice.buscar(consulta, k=self.k)

        if not resultados:
            return RespostaAgente(
                resposta=MENSAGEM_SEM_CONTEXTO,
                provedor="sem_contexto",
                trechos_recuperados=0,
                tempo_ms=int((time.perf_counter() - inicio) * 1000),
            )

        contexto = self._montar_contexto(resultados)
        prompt_usuario = (
            f"{self._montar_historico(historico)}"
            "TRECHOS DOS DOCUMENTOS:\n"
            f"{contexto}\n\n"
            "PERGUNTA DA CLIENTE:\n"
            f"{pergunta}\n\n"
            "Responda seguindo as regras do sistema e cite as fontes usadas."
        )

        try:
            saida = self.roteador.gerar(PROMPT_SISTEMA, prompt_usuario)
            texto, provedor, tentativas = saida.texto, saida.provedor, saida.tentativas
        except ProvedorIndisponivel as erro:
            log.error("todos os provedores falharam: %s", erro)
            texto = MENSAGEM_SEM_CONTEXTO
            provedor = "indisponivel"
            tentativas = [str(erro)]

        fontes = [
            Fonte(
                documento=r.trecho.fonte,
                referencia=r.trecho.referencia,
                pontuacao=r.pontuacao,
                tipo=r.trecho.tipo,
            )
            for r in resultados
        ]

        return RespostaAgente(
            resposta=texto.strip(),
            fontes=fontes,
            provedor=provedor,
            trechos_recuperados=len(resultados),
            tempo_ms=int((time.perf_counter() - inicio) * 1000),
            tentativas=tentativas,
        )


PERGUNTAS_EXEMPLO = [
    "Estou grávida, quais ativos do catálogo eu posso usar?",
    "Qual protetor solar vocês têm para pele oleosa até R$ 120?",
    "Posso usar retinol e ácido glicólico na mesma noite?",
    "Em quantos dias chega em Manaus e quanto custa o frete?",
    "Comprei um sérum, abri e tive alergia. Consigo devolver?",
    "O que é niacinamida e para que serve?",
    "Óleo de coco no rosto pode causar cravos?",
    "Como faço para excluir meus dados do site?",
    "Quais produtos de vocês são veganos e cruelty-free?",
    "Meu pedido está parado no rastreio há 12 dias. E agora?",
]
