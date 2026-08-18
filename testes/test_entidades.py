"""Testes da regra de cobertura mínima e da exceção por nome de entidade.

Regressão de dois defeitos reais encontrados durante o desenvolvimento:

1. "qual a escalação do time hoje" recuperava a ficha da oxibenzona, porque a
   palavra "hoje" aparece por acaso naquele texto.
2. Ao corrigir o primeiro, "o que é niacinamida e para que serve" passou a
   retornar zero trechos: só "niacinamida" existe no índice, e a regra exigia
   dois acertos.
"""

from __future__ import annotations

import pytest

from app.indice import obter_indice


@pytest.fixture(scope="module")
def indice():
    return obter_indice()


def test_nomes_de_entidade_foram_indexados(indice):
    assert "niacinamida" in indice.termos_entidade
    assert "retinol" in indice.termos_entidade
    assert "hoje" not in indice.termos_entidade


@pytest.mark.parametrize(
    "consulta,esperado",
    [
        ("o que é niacinamida e para que serve", "Niacinamide"),
        ("bakuchiol", "Bakuchiol"),
        ("para que serve o esqualano", "Squalane"),
        ("alantoína faz o quê", "Allantoin"),
    ],
)
def test_um_acerto_em_nome_de_ingrediente_e_suficiente(indice, consulta, esperado):
    resultados = indice.buscar(consulta, k=5)
    assert resultados, f"nada recuperado para: {consulta}"
    incis = [r.trecho.metadados.get("inci") for r in resultados]
    assert esperado in incis


def test_busca_por_codigo_de_produto(indice):
    resultados = indice.buscar("LB-0201", k=3)
    assert resultados
    assert resultados[0].trecho.metadados.get("codigo") == "LB-0201"


@pytest.mark.parametrize(
    "consulta",
    [
        "qual a escalação do time hoje",
        "receita de bolo de cenoura",
        "qual o horário do voo amanhã",
    ],
)
def test_palavra_solta_fora_do_dominio_nao_recupera(indice, consulta):
    assert indice.buscar(consulta, k=5) == []
