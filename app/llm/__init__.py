"""Camada de LLM: contrato, provedores e roteador com fallback."""

from .base import Provedor, ProvedorIndisponivel
from .roteador import Roteador, SaidaLLM

__all__ = ["Provedor", "ProvedorIndisponivel", "Roteador", "SaidaLLM"]
