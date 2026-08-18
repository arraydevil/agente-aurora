"""Testes do desvio de conversa social.

Regressão de um defeito de acolhimento: digitar "olá" no chat devolvia
"não encontrei essa informação nos documentos da Lumina Beauty", porque a
saudação caía na guarda de escopo como se fosse pergunta fora do domínio.
"""

from __future__ import annotations

import pytest

from app.agente import AgenteAurora, detectar_intencao_social


@pytest.mark.parametrize(
    "mensagem",
    ["olá", "Oi", "oii", "bom dia", "Boa noite!", "opa", "e aí", "tudo bem?", "oi aurora"],
)
def test_reconhece_saudacao(mensagem):
    assert detectar_intencao_social(mensagem) == "saudacao"


@pytest.mark.parametrize("mensagem", ["obrigada", "valeu!", "muito obrigada", "vlw"])
def test_reconhece_agradecimento(mensagem):
    assert detectar_intencao_social(mensagem) == "agradecimento"


@pytest.mark.parametrize("mensagem", ["tchau", "até mais", "falou", "até logo!"])
def test_reconhece_despedida(mensagem):
    assert detectar_intencao_social(mensagem) == "despedida"


@pytest.mark.parametrize(
    "mensagem",
    [
        "bom dia, qual o prazo de entrega para Recife?",
        "oi, posso usar retinol grávida?",
        "olá! quanto custa o protetor solar de vocês?",
        "obrigada, mas ainda tenho dúvida sobre a troca do sérum",
    ],
)
def test_saudacao_com_pergunta_segue_para_a_busca(mensagem):
    """Cumprimento acompanhado de pergunta real não pode virar resposta social."""
    assert detectar_intencao_social(mensagem) is None


@pytest.mark.parametrize(
    "mensagem",
    ["qual o prazo de troca?", "niacinamida serve pra quê?", "quero um protetor solar"],
)
def test_pergunta_normal_nao_e_social(mensagem):
    assert detectar_intencao_social(mensagem) is None


def test_agente_responde_saudacao_sem_mensagem_de_erro():
    resposta = AgenteAurora().responder("olá")
    assert resposta.provedor == "saudacao"
    assert "não encontrei" not in resposta.resposta.lower()
    assert resposta.trechos_recuperados == 0
    assert "💗" in resposta.resposta


def test_agente_ainda_recusa_pergunta_fora_do_escopo():
    resposta = AgenteAurora().responder("quem ganhou a copa de 1982")
    assert resposta.provedor == "sem_contexto"
