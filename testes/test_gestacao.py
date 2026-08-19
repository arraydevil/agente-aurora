"""Testes da salvaguarda de gestação.

Regra de segurança que não pode depender de o modelo lembrar: sempre que a
pessoa levanta gestação ou amamentação, a resposta precisa encaminhá-la a quem
acompanha o pré-natal. Em teste adversarial, o modelo respondeu "liberados para
uso na gestação" e encerrou sem nenhum encaminhamento — correto pelo documento,
insuficiente para alguém decidindo o que passar na pele grávida.
"""

from __future__ import annotations

import pytest

from app.agente import AVISO_GESTACAO, garantir_encaminhamento_medico


@pytest.mark.parametrize(
    "pergunta",
    [
        "Estou grávida, quais ativos posso usar?",
        "posso usar isso na gestação?",
        "sou gestante, esse sérum serve?",
        "estou amamentando, pode?",
        "no pós-parto posso voltar com o retinol?",
        "GRAVIDA POSSO USAR ACIDO?",
    ],
)
def test_acrescenta_encaminhamento_quando_falta(pergunta):
    resposta = "Esse produto é liberado na gestação e custa R$ 79,90."
    saida = garantir_encaminhamento_medico(pergunta, resposta)
    assert saida.endswith(AVISO_GESTACAO)
    assert resposta in saida  # o conteúdo original é preservado


@pytest.mark.parametrize(
    "encerramento",
    [
        "Converse com seu dermatologista antes de usar.",
        "Confirme com quem acompanha o seu pré-natal.",
        "Vale checar com sua obstetra.",
        "Procure orientação médica.",
    ],
)
def test_nao_duplica_quando_ja_encaminha(encerramento):
    resposta = f"Esse ativo é liberado. {encerramento}"
    assert garantir_encaminhamento_medico("estou grávida, posso usar?", resposta) == resposta


@pytest.mark.parametrize(
    "pergunta",
    [
        "qual o prazo de entrega para Recife?",
        "o que é niacinamida?",
        "quero um protetor solar para pele oleosa",
        "posso trocar um produto aberto?",
    ],
)
def test_nao_interfere_em_pergunta_sem_gestacao(pergunta):
    resposta = "Resposta qualquer sobre o catálogo."
    assert garantir_encaminhamento_medico(pergunta, resposta) == resposta


def test_aviso_nao_promete_seguranca():
    """O aviso não pode dizer que está tudo bem — ele devolve a decisão ao médico."""
    assert "pré-natal" in AVISO_GESTACAO
    for promessa in ("sem preocupação", "sem risco", "pode usar tranquila"):
        assert promessa not in AVISO_GESTACAO.lower()
