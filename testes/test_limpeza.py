"""Testes da limpeza de marcação nas respostas do agente.

O prompt pede texto puro, mas modelo de linguagem escorrega. Sem esta camada,
asterisco e tabela em pipes apareciam literalmente na tela da cliente.
"""

from __future__ import annotations

from app.agente import limpar_resposta


def test_remove_negrito_e_italico():
    assert limpar_resposta("O **retinol** é um *ativo* potente.") == (
        "O retinol é um ativo potente."
    )


def test_remove_titulo_e_crase():
    assert limpar_resposta("## Opções\nUse o `LB-0201`.") == "Opções\nUse o LB-0201."


def test_tabela_vira_lista():
    entrada = (
        "Opções para você:\n"
        "| Código | Produto | Preço |\n"
        "|--------|---------|-------|\n"
        "| LB-0201 | Protetor Toque Seco | R$ 109,90 |\n"
        "| LB-0204 | Protetor Spray | R$ 89,90 |"
    )
    esperado = (
        "Opções para você:\n"
        "- Código, Produto, Preço\n"
        "- LB-0201, Protetor Toque Seco, R$ 109,90\n"
        "- LB-0204, Protetor Spray, R$ 89,90"
    )
    assert limpar_resposta(entrada) == esperado


def test_corta_bloco_de_fontes_com_asterisco():
    entrada = (
        "Pode usar sim, é liberado.\n\n"
        "**Fontes**\n"
        "[3] PRODUTO LB-0201 — Protetor Solar\n"
        "[4] glossario_ingredientes.csv"
    )
    assert limpar_resposta(entrada) == "Pode usar sim, é liberado."


def test_corta_bloco_de_fontes_com_dois_pontos():
    entrada = "Chega em 3 a 5 dias úteis.\n\nFontes: politicas_lumina.pdf — seção 4.2"
    assert limpar_resposta(entrada) == "Chega em 3 a 5 dias úteis."


def test_remove_marcadores_de_citacao():
    entrada = "A niacinamida controla a oleosidade【2】 e reduz manchas [4]."
    assert limpar_resposta(entrada) == "A niacinamida controla a oleosidade e reduz manchas."


def test_remove_regra_horizontal():
    assert limpar_resposta("Antes\n---\nDepois") == "Antes\nDepois"


def test_preserva_lista_com_traco():
    entrada = (
        "Duas opções:\n"
        "- Protetor Toque Seco, R$ 109,90 (código LB-0201)\n"
        "- Protetor Spray, R$ 89,90 (código LB-0204)"
    )
    assert limpar_resposta(entrada) == entrada


def test_preserva_texto_ja_limpo():
    entrada = "Você pode devolver em até 30 dias.\n\nQualquer dúvida, é só chamar."
    assert limpar_resposta(entrada) == entrada


def test_nao_confunde_a_palavra_fontes_no_meio_da_frase():
    entrada = "Nossas fontes de vitamina C são estáveis e o produto é vegano."
    assert limpar_resposta(entrada) == entrada
