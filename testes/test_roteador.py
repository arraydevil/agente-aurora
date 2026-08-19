"""Testes do roteador de provedores.

Regressão de um defeito encontrado em produção: com `PROVEDORES_LLM` definida
como string vazia, a cascata inteira era descartada em silêncio. Sobrava só o
modo extrativo, e a aplicação parecia saudável — respondia 200, com trechos
corretos, só que sem nenhuma geração em linguagem natural.
"""

from __future__ import annotations

import pytest

from app.llm.roteador import ORDEM_PADRAO, RespostaExtrativa, Roteador


def nomes(roteador: Roteador) -> list[str]:
    return [p.nome for p in roteador.provedores]


def test_ordem_explicita_e_respeitada():
    assert nomes(Roteador("gemini,groq")) == ["gemini", "groq", "extrativo"]


def test_ordem_padrao_quando_nao_ha_configuracao(monkeypatch):
    monkeypatch.delenv("PROVEDORES_LLM", raising=False)
    assert nomes(Roteador()) == [*ORDEM_PADRAO.split(","), "extrativo"]


def test_variavel_vazia_cai_na_ordem_padrao(monkeypatch):
    monkeypatch.setenv("PROVEDORES_LLM", "")
    assert nomes(Roteador()) == [*ORDEM_PADRAO.split(","), "extrativo"]


def test_nome_invalido_cai_na_ordem_padrao(monkeypatch):
    monkeypatch.setenv("PROVEDORES_LLM", "bedrock,vertex")
    assert nomes(Roteador()) == [*ORDEM_PADRAO.split(","), "extrativo"]


def test_espaco_sobrando_nao_quebra(monkeypatch):
    monkeypatch.setenv("PROVEDORES_LLM", "  groq , GEMINI  ")
    assert nomes(Roteador()) == ["groq", "gemini", "extrativo"]


def test_nome_invalido_no_meio_e_ignorado(monkeypatch):
    monkeypatch.setenv("PROVEDORES_LLM", "groq,bedrock,gemini")
    assert nomes(Roteador()) == ["groq", "gemini", "extrativo"]


def test_extrativo_e_sempre_o_ultimo_degrau():
    assert isinstance(Roteador("groq").provedores[-1], RespostaExtrativa)


# --------------------------------------------------------- modo extrativo


@pytest.fixture
def prompt_com_gestacao() -> str:
    return (
        "TRECHOS DOS DOCUMENTOS:\n"
        "PRODUTO LB-0004 — Retinol 0,3% em Sérum Encapsulado.\n"
        "Gestação: contraindicado na gestação e na amamentação.\n\n"
        "PERGUNTA DA CLIENTE:\nEstou grávida, quais ativos posso usar?"
    )


def test_extrativo_avisa_que_nao_e_recomendacao(prompt_com_gestacao):
    """Os trechos mais parecidos com a pergunta podem ser o oposto do que a
    pessoa quer. Perguntar o que pode usar grávida recupera justamente o que é
    contraindicado, então a resposta precisa dizer isso em voz alta."""
    texto = RespostaExtrativa().gerar("", prompt_com_gestacao)
    assert "NÃO é uma recomendação" in texto
    assert "dermatologista" in texto
    assert "Retinol" in texto  # o conteúdo recuperado continua sendo mostrado


def test_extrativo_sem_trechos_encaminha_para_o_humano():
    texto = RespostaExtrativa().gerar("", "PERGUNTA DA CLIENTE:\nalgo")
    assert "atendimento@luminabeauty.com.br" in texto


def test_extrativo_esta_sempre_disponivel():
    assert RespostaExtrativa().disponivel() is True
