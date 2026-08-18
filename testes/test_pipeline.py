"""Testes do pipeline de RAG: ingestão, recuperação e resposta do agente.

Rodar:  pytest -q
"""

from __future__ import annotations

import pytest

from app.agente import AgenteAurora
from app.indice import obter_indice, tokenizar
from app.ingestao import (
    carregar_catalogo,
    carregar_documentos,
    carregar_glossario,
    carregar_pdf,
    resumo_fontes,
)


# --------------------------------------------------------------- ingestão


def test_pdf_gera_trechos_com_pagina():
    trechos = carregar_pdf()
    assert len(trechos) > 10
    assert all(t.tipo == "pdf" for t in trechos)
    assert all("p. " in t.referencia for t in trechos)


def test_pdf_preserva_conteudo_critico():
    texto = " ".join(t.texto for t in carregar_pdf()).lower()
    for esperado in ["7 dias corridos", "r$ 199,00", "lgpd", "peróxido de benzoíla"]:
        assert esperado in texto, f"conteúdo perdido na extração: {esperado}"


def test_catalogo_converte_tipos():
    produtos = carregar_catalogo()
    assert len(produtos) >= 40
    primeiro = produtos[0]
    assert isinstance(primeiro.metadados["preco"], float)
    assert isinstance(primeiro.metadados["estoque"], int)
    assert primeiro.metadados["codigo"].startswith("LB-")


def test_glossario_carrega_ingredientes():
    ingredientes = carregar_glossario()
    assert len(ingredientes) >= 100
    incis = {t.metadados["inci"] for t in ingredientes}
    assert {"Niacinamide", "Retinol", "Salicylic Acid"} <= incis


def test_resumo_cobre_os_tres_documentos():
    resumo = resumo_fontes()
    assert set(resumo["por_documento"]) == {
        "politicas_lumina.pdf",
        "catalogo_produtos.csv",
        "glossario_ingredientes.csv",
    }
    assert resumo["total_trechos"] == len(carregar_documentos())


# -------------------------------------------------------------- tokenização


def test_tokenizacao_remove_acento_e_plural():
    assert tokenizar("Ácidos Esfoliantes") == ["acido", "esfoliant"]


def test_expansao_de_sinonimos():
    tokens = tokenizar("estou grávida", expandir=True)
    assert "gestacao" in tokens or "gestante" in tokens


def test_palavras_vazias_sao_descartadas():
    assert tokenizar("eu posso usar isso") == ["usar"]


# -------------------------------------------------------------- recuperação


@pytest.mark.parametrize(
    "consulta,esperado_em_referencia",
    [
        ("posso usar retinol e ácido glicólico juntos", "7.1"),
        ("tive alergia ao produto, posso devolver", "3.4"),
        ("qual o valor do frete grátis", "4."),
        ("como excluo meus dados pessoais", "2."),
    ],
)
def test_busca_encontra_a_secao_certa(consulta, esperado_em_referencia):
    resultados = obter_indice().buscar(consulta, k=3)
    assert resultados, f"nada recuperado para: {consulta}"
    referencias = " ".join(r.trecho.referencia for r in resultados)
    assert esperado_em_referencia in referencias


def test_busca_recupera_produto_do_catalogo():
    resultados = obter_indice().buscar("protetor solar para pele oleosa", k=5)
    codigos = [
        r.trecho.metadados.get("codigo")
        for r in resultados
        if r.trecho.fonte == "catalogo_produtos.csv"
    ]
    assert codigos, "nenhum produto recuperado"


def test_busca_recupera_ingrediente_do_glossario():
    resultados = obter_indice().buscar("óleo de coco entope os poros?", k=5)
    incis = [r.trecho.metadados.get("inci") for r in resultados]
    assert "Cocos Nucifera Oil" in incis


def test_pergunta_fora_do_escopo_nao_recupera_nada():
    resultados = obter_indice().buscar("qual a escalação do time hoje", k=5)
    assert resultados == []


def test_limite_por_fonte_garante_diversidade():
    resultados = obter_indice().buscar(
        "produto para manchas e política de troca", k=6, limite_por_fonte=2
    )
    contagem: dict[str, int] = {}
    for resultado in resultados:
        contagem[resultado.trecho.fonte] = contagem.get(resultado.trecho.fonte, 0) + 1
    assert all(quantidade <= 2 for quantidade in contagem.values())


# ------------------------------------------------------------------ agente


def test_agente_responde_com_fontes():
    """Sem chave de LLM configurada o roteador cai no modo extrativo,
    mas a resposta e as fontes continuam sendo produzidas."""
    resposta = AgenteAurora().responder("Em quanto tempo chega o pedido no Nordeste?")
    assert resposta.resposta.strip()
    assert resposta.fontes
    assert resposta.trechos_recuperados > 0
    assert all(f.documento.endswith((".pdf", ".csv")) for f in resposta.fontes)


def test_agente_admite_quando_nao_sabe():
    resposta = AgenteAurora().responder("quem ganhou a copa de 1982")
    assert resposta.provedor == "sem_contexto"
    assert "não encontrei" in resposta.resposta.lower()


def test_agente_com_pergunta_vazia_nao_quebra():
    resposta = AgenteAurora().responder("   ")
    assert resposta.resposta
    assert resposta.trechos_recuperados == 0
