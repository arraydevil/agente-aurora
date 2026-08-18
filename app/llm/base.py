"""Contrato comum entre os provedores de LLM."""

from __future__ import annotations

from typing import Protocol


class ProvedorIndisponivel(RuntimeError):
    """Provedor nao configurado ou com falha; o roteador deve tentar o proximo."""


class Provedor(Protocol):
    nome: str

    def disponivel(self) -> bool:
        """True quando ha credencial e configuracao suficientes para tentar a chamada."""
        ...

    def gerar(self, sistema: str, usuario: str) -> str:
        """Retorna a resposta em texto ou levanta ProvedorIndisponivel."""
        ...
