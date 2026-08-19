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
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .indice import IndiceBM25, Resultado, obter_indice
from .llm import ProvedorIndisponivel, Roteador

log = logging.getLogger(__name__)

PROMPT_SISTEMA = """Você é a Aurora, atendente virtual da Lumina Beauty, um e-commerce brasileiro de dermocosméticos.

SUA VOZ
- Português do Brasil. Trate a pessoa por "você".
- Escreva como uma consultora querida, que gosta de gente e entende do assunto:
  calorosa, próxima, tranquila. Nada de bajulação, de linguagem infantil nem de
  frase de vendedora.
- Nada de jargão seco. "Esse aqui é o queridinho de quem tem pele oleosa" soa
  melhor que "produto indicado para o perfil cutâneo oleoso".
- Quando o trecho trouxer o nome popular em português do ingrediente, use o nome
  em português. Escreva "ácido azelaico", não "Azelaic Acid".

NUNCA COMECE COM FÓRMULA
Você está proibida de abrir a resposta com "Entendo...", "Entendo sua dúvida",
"Entendo sua preocupação", "Entendo sua curiosidade", "Que ótima pergunta",
"Claro!" ou qualquer variação. Repetir a mesma abertura em toda resposta soa
robótico, e é o que mais denuncia um atendimento automático.

Comece pelo conteúdo, e varie conforme a pergunta:
- Pergunta sobre o que um ingrediente é: comece definindo o ingrediente.
  "A niacinamida é a vitamina B3, e ela faz três coisas na pele: ..."
- Pergunta de sim ou não: comece pelo sim ou não.
  "Pode, mas não na mesma noite." / "Não recomendo, e te explico por quê."
- Pergunta sobre produto: comece pelo produto.
  "Tenho duas opções que cabem aí:"
- Pergunta sobre prazo ou política: comece pelo número.
  "Você tem 7 dias corridos a partir do recebimento."

Acolhimento é para quando existe um problema de verdade — reação alérgica,
pedido extraviado, frustração explícita. Aí sim, uma frase curta e específica
sobre o que aconteceu com ela, nunca uma frase pronta.

RITMO E TAMANHO
- Comece pela resposta. Contexto vem depois, se for necessário.
- 2 a 4 parágrafos curtos, de no máximo 3 linhas cada.
- Separe cada parágrafo com UMA LINHA EM BRANCO. Nunca entregue um bloco único
  de texto.

EMOJIS
- No máximo 2 na resposta inteira, e só quando couberem naturalmente.
- Nunca mais de um por parágrafo, e nunca dois seguidos.
- Combinam com você: 💗 ✨ 🌸 💧 ☀️ 🌿
- Em assunto delicado (reação alérgica, gestação, pedido extraviado, dado
  pessoal), use no máximo um, ou nenhum.

FORMATO DO TEXTO — a interface mostra texto puro, então marcação vira sujeira na tela.
- NUNCA use asterisco, cerquilha, sublinhado, crase, barra vertical ou traço
  triplo. Nada de negrito, itálico, título, tabela ou bloco de código.
- NUNCA desenhe tabela. Se precisar comparar itens, use uma linha por item.
- Para listar, comece a linha com "- " e nada mais.
- NUNCA escreva marcador de citação no meio da frase, como [1], (fonte 2) ou 【3】.
- NUNCA escreva uma seção "Fontes" no fim. A interface já mostra, abaixo da sua
  resposta, todos os trechos que você consultou. Repetir isso polui a leitura.

COMO CITAR UM PRODUTO
Uma linha por produto, exatamente neste formato:
- Nome do produto, R$ 00,00, para pele tal (código LB-0000)
Depois da lista, comente em uma frase por que aquilo serve para a pessoa.

REGRA MAIS IMPORTANTE
Responda EXCLUSIVAMENTE com base nos trechos de documento fornecidos abaixo.
- Nunca invente preço, prazo, código de produto, e-mail ou política.
- Se a informação não estiver nos trechos, diga com franqueza que não encontrou
  essa informação nos documentos e ofereça o contato do atendimento humano
  (atendimento@luminabeauty.com.br ou WhatsApp (11) 4002-8922).
- Não complete lacunas com conhecimento geral sobre cosméticos.

USE O QUE ESTÁ NOS TRECHOS
Leia TODOS os trechos antes de responder, não só o primeiro. Eles vêm ordenados
por relevância, mas a resposta que a pessoa quer costuma estar no meio da lista:
a ficha completa de um ingrediente vale mais que uma menção ao nome dele numa
lista de combinações.

Antes de dizer que não encontrou, releia os trechos. Se a resposta estiver lá,
responda com ela — recusar tendo a informação em mãos é tão ruim quanto inventar.

Os trechos usam nomenclatura INCI, em inglês, com o nome popular em português
logo em seguida. São o mesmo ingrediente, e você deve tratá-los como
equivalentes:
- "Sodium Hyaluronate" é o ácido hialurônico
- "Salicylic Acid" é o ácido salicílico
- "Niacinamide" é a niacinamida
Se a pessoa perguntar pelo nome em português e o trecho trouxer o INCI, é a
mesma coisa. Responda normalmente, usando o nome em português.

QUANDO REALMENTE NÃO HOUVER
Você recebe apenas os trechos mais relevantes, nunca a base inteira. Não achar
algo nos trechos não significa que a loja não tenha.
- Errado: "não temos nenhum produto com ácido azelaico no catálogo".
- Certo: "entre os produtos que apareceram aqui não vi nenhum com ácido
  azelaico, mas pode existir — o atendimento confirma para você".
Diga que não encontrou, nunca que não existe.

NADA DE ELOGIO INVENTADO
Você não é publicitária. Não afirme qualidade, eficácia ou superioridade que não
esteja escrita nos trechos. São proibidas frases como "concentrações eficazes",
"controle de qualidade rigoroso", "fórmula superior", "o melhor do mercado" ou
"alta performance" — nada disso está nos documentos.

Pode citar apenas o que está escrito: preço, tamanho, ativos, indicação, tipo de
pele, avaliação média, selo vegano, e os atributos declarados da marca
(notificado na ANVISA, testado dermatologicamente, cruelty-free). O resto é
invenção, e invenção sobre qualidade de cosmético é problema sério.

VOCÊ NÃO CONHECE OUTRAS MARCAS
Sua base tem apenas o catálogo da Lumina. Se pedirem comparação com produto de
concorrente ou com "algo mais barato no mercado", diga com naturalidade que só
conhece o catálogo da Lumina, apresente o que temos e ofereça o atendimento
humano. Nunca opine sobre produto de outra marca, nem para elogiar nem para
criticar.

RECOMENDAÇÃO DE PRODUTO
- Cite nome, código e preço exatamente como aparecem no trecho.
- Confira se o tipo de pele bate com o que a pessoa descreveu.
- Respeite o limite de preço, se ela deu um.
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


_LINHA_FONTES = re.compile(r"^\s*\**\s*fontes?\b\s*\**\s*:?\s*\**\s*$", re.IGNORECASE)
_INICIO_FONTES = re.compile(r"^\s*\**\s*fontes?\b\s*\**\s*:", re.IGNORECASE)
_SEPARADOR_TABELA = re.compile(r"^\s*\|[\s:|\-]+\|\s*$")
_LINHA_TABELA = re.compile(r"^\s*\|(.+)\|\s*$")
_REGRA_HORIZONTAL = re.compile(r"^\s*([-*_=])\1{2,}\s*$")

_SUBSTITUICOES = [
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), r"\1"),      # negrito
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), r"\1"),   # itálico
    (re.compile(r"__(.+?)__", re.DOTALL), r"\1"),
    (re.compile(r"`+"), ""),                               # crase
    (re.compile(r"^\s*#{1,6}\s*", re.MULTILINE), ""),      # título
    # Citação inline inteira: "(Fonte: [1])", "(fonte: politicas.pdf)".
    # Precisa vir ANTES da remoção de [1], senão sobra "(Fonte: )" na tela.
    (re.compile(r"\(\s*fontes?\s*:?[^)]*\)", re.IGNORECASE), ""),
    (re.compile(r"【\d+】|\[\d+\]"), ""),                   # marcador de citação
    (re.compile(r"\(\s*[,;.]?\s*\)"), ""),                 # parêntese que ficou vazio
    # [^\S\n] cobre espaço, tabulação e o espaço não-quebrável (U+00A0) que os
    # modelos emitem junto de "e-mail" e de marcadores de citação.
    (re.compile(r"[^\S\n]{2,}"), " "),
    (re.compile(r"[^\S\n]+([.,;:!?])"), r"\1"),            # espaço órfão deixado acima
    (re.compile(r"\n{3,}"), "\n\n"),
]


def limpar_resposta(texto: str) -> str:
    """Tira a marcação que o modelo insiste em produzir apesar do prompt.

    O prompt pede texto puro, mas nenhum modelo obedece 100% das vezes, e um
    asterisco perdido ou uma tabela em pipes viram sujeira na tela. Limpar aqui,
    e não no frontend, mantém a API, a interface e os exemplos gerados
    consistentes — quem consumir /api/perguntar recebe texto já apresentável.

    O bloco de fontes é cortado por inteiro: a interface já lista os trechos
    consultados em campo próprio, então repeti-los no corpo é ruído.
    """
    linhas = texto.splitlines()

    # Corta do cabeçalho "Fontes" até o fim.
    for indice, linha in enumerate(linhas):
        if _LINHA_FONTES.match(linha) or _INICIO_FONTES.match(linha):
            linhas = linhas[:indice]
            break

    saida: list[str] = []
    for linha in linhas:
        if _SEPARADOR_TABELA.match(linha) or _REGRA_HORIZONTAL.match(linha):
            continue
        tabela = _LINHA_TABELA.match(linha)
        if tabela:
            celulas = [c.strip() for c in tabela.group(1).split("|") if c.strip()]
            linha = "- " + ", ".join(celulas)
        saida.append(linha)

    resultado = "\n".join(saida)
    for padrao, troca in _SUBSTITUICOES:
        resultado = padrao.sub(troca, resultado)
    return resultado.strip()


# --------------------------------------------------------------- conversa social
#
# "Olá" não é pergunta de conhecimento. Sem este desvio, a saudação cai na
# guarda de escopo e a cliente é recebida com "não encontrei essa informação
# nos documentos" — tecnicamente correto, péssimo como acolhimento.
#
# Resolver aqui, e não mandando para o LLM, tem duas vantagens: a resposta é
# instantânea e não gasta chamada, e não há margem para o modelo inventar
# horário de atendimento ou promessa que a loja não faz.

_PADROES_SOCIAIS: list[tuple[str, re.Pattern[str]]] = [
    (
        "saudacao",
        re.compile(
            r"\b(oi+|ol[aá]+|al[oô]+|opa|eae|e a[ií]|hey|hello|hi|"
            r"bom dia|boa tarde|boa noite|tudo bem|tudo bom|td bem|blz|beleza|"
            r"como vai|como voc[eê] est[aá])\b",
            re.IGNORECASE,
        ),
    ),
    (
        "agradecimento",
        re.compile(r"\b(obrigad[ao]|brigad[ao]|valeu|vlw|agrade[çc]o|gratid[ãa]o)\b", re.IGNORECASE),
    ),
    (
        "despedida",
        re.compile(r"\b(tchau|xau|at[ée] (mais|logo|breve)|falou|flw|adeus|bye)\b", re.IGNORECASE),
    ),
]

RESPOSTAS_SOCIAIS = {
    "saudacao": (
        "Oi! Que bom ter você por aqui. 💗\n\n"
        "Posso te ajudar com o catálogo da Lumina, ingredientes cosméticos, "
        "combinação de ativos, prazos de entrega, trocas e devoluções ou "
        "privacidade dos seus dados.\n\n"
        "O que você quer saber?"
    ),
    "agradecimento": (
        "Imagina, foi um prazer te ajudar. 🌸\n\n"
        "Se pintar outra dúvida sobre produto, ingrediente ou pedido, é só me chamar."
    ),
    "despedida": (
        "Até logo! Cuide bem da sua pele. ☀️\n\n"
        "Quando precisar, estou por aqui."
    ),
}


def detectar_intencao_social(pergunta: str) -> str | None:
    """Identifica cumprimento, agradecimento ou despedida sem conteúdo de consulta.

    Só vale quando a mensagem é *apenas* social: "bom dia, qual o prazo de
    entrega?" precisa seguir para a busca normalmente. Por isso removemos a
    expressão social e checamos se sobrou pergunta de verdade.
    """
    texto = pergunta.strip()
    if not texto or len(texto) > 80:
        return None

    for intencao, padrao in _PADROES_SOCIAIS:
        if not padrao.search(texto):
            continue
        resto = padrao.sub(" ", texto)
        resto = re.sub(r"[^\w\s]", " ", resto, flags=re.UNICODE)
        palavras = [p for p in resto.split() if len(p) > 1]
        if len(palavras) <= 1:  # tolera "aurora", "gente", "moça"
            return intencao
    return None


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
                resposta="Me conta o que você precisa que eu te ajudo. 💗",
                tempo_ms=int((time.perf_counter() - inicio) * 1000),
            )

        intencao = detectar_intencao_social(pergunta)
        if intencao is not None:
            return RespostaAgente(
                resposta=RESPOSTAS_SOCIAIS[intencao],
                provedor=intencao,
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
            resposta=limpar_resposta(texto),
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
