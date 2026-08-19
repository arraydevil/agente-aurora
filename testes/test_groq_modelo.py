"""Testes da recuperação automática quando o modelo da Groq é aposentado.

Regressão de uma falha que derrubou a aplicação em produção: a Groq
descontinuou o modelo configurado e passou a devolver 404 em toda chamada. Um
nome de modelo fixo — no código ou numa variável de ambiente — transforma a
aposentadoria de um modelo em indisponibilidade do agente.
"""

from __future__ import annotations

import pytest

from app.llm.base import ProvedorIndisponivel
from app.llm.reserva import Groq

MODELOS_DA_CONTA = {
    "data": [
        {"id": "meta-llama/llama-prompt-guard-2-22m", "active": True, "context_window": 512},
        {"id": "openai/gpt-oss-safeguard-20b", "active": True, "context_window": 131072},
        {"id": "qwen/qwen3.6-27b", "active": True, "context_window": 131072},
        {"id": "openai/gpt-oss-120b", "active": True, "context_window": 131072},
        {"id": "allam-2-7b", "active": True, "context_window": 4096},
    ]
}


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_teste")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # aposentado
    return Groq()


def test_descoberta_ignora_modelos_que_nao_conversam(groq, monkeypatch):
    monkeypatch.setattr(
        "app.llm.reserva.httpx.Client.get",
        lambda self, url, headers=None: _RespostaFalsa(MODELOS_DA_CONTA),
    )
    escolhido = groq._descobrir_modelo()
    assert escolhido == "openai/gpt-oss-120b"
    assert "guard" not in escolhido


def test_descoberta_cai_no_maior_contexto_sem_preferido(groq, monkeypatch):
    catalogo = {
        "data": [
            {"id": "modelo-pequeno", "active": True, "context_window": 8192},
            {"id": "modelo-grande", "active": True, "context_window": 65536},
            {"id": "modelo-guard", "active": True, "context_window": 131072},
        ]
    }
    monkeypatch.setattr(
        "app.llm.reserva.httpx.Client.get",
        lambda self, url, headers=None: _RespostaFalsa(catalogo),
    )
    assert groq._descobrir_modelo() == "modelo-grande"


def test_404_troca_de_modelo_e_repete(groq, monkeypatch):
    chamadas: list[str] = []

    def pedir_falso(self, modelo, sistema, usuario):
        chamadas.append(modelo)
        if modelo == "llama-3.3-70b-versatile":
            raise ProvedorIndisponivel("Client error '404 Not Found' for url ...")
        return {"choices": [{"message": {"content": "resposta gerada"}}]}

    monkeypatch.setattr(Groq, "_pedir", pedir_falso)
    monkeypatch.setattr(Groq, "_descobrir_modelo", lambda self: "openai/gpt-oss-120b")

    assert groq.gerar("sistema", "usuario") == "resposta gerada"
    assert chamadas == ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]
    assert groq.modelo == "openai/gpt-oss-120b"  # a troca fica valendo


def test_erro_que_nao_e_404_nao_dispara_descoberta(groq, monkeypatch):
    def pedir_falso(self, modelo, sistema, usuario):
        raise ProvedorIndisponivel("Client error '401 Unauthorized'")

    def nao_deveria_ser_chamado(self):
        raise AssertionError("descoberta de modelo não deve rodar em erro de credencial")

    monkeypatch.setattr(Groq, "_pedir", pedir_falso)
    monkeypatch.setattr(Groq, "_descobrir_modelo", nao_deveria_ser_chamado)

    with pytest.raises(ProvedorIndisponivel, match="401"):
        groq.gerar("sistema", "usuario")


def test_sem_substituto_o_erro_original_e_preservado(groq, monkeypatch):
    monkeypatch.setattr(
        Groq, "_pedir",
        lambda self, m, s, u: (_ for _ in ()).throw(ProvedorIndisponivel("404 Not Found")),
    )
    monkeypatch.setattr(Groq, "_descobrir_modelo", lambda self: None)

    with pytest.raises(ProvedorIndisponivel, match="não achei substituto"):
        groq.gerar("sistema", "usuario")


def test_sem_chave_falha_antes_de_qualquer_chamada(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ProvedorIndisponivel, match="GROQ_API_KEY ausente"):
        Groq().gerar("sistema", "usuario")


class _RespostaFalsa:
    def __init__(self, dados: dict) -> None:
        self._dados = dados

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._dados
