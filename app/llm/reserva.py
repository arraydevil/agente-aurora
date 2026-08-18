"""Provedores de reserva via REST puro (sem SDK).

Entram em acao quando a OCI Generative AI nao responde: conta ainda em
verificacao, credencial ausente, limite de servico ou indisponibilidade.
"""

from __future__ import annotations

import os

import httpx

from .base import ProvedorIndisponivel

TEMPO_LIMITE = httpx.Timeout(60.0, connect=10.0)


class Groq:
    nome = "groq"

    def __init__(self) -> None:
        self.chave = os.getenv("GROQ_API_KEY", "").strip()
        self.modelo = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    def disponivel(self) -> bool:
        return bool(self.chave)

    def gerar(self, sistema: str, usuario: str) -> str:
        if not self.chave:
            raise ProvedorIndisponivel("GROQ_API_KEY ausente")

        corpo = {
            "model": self.modelo,
            "temperature": 0.35,
            "max_tokens": 1400,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
        }
        try:
            with httpx.Client(timeout=TEMPO_LIMITE) as cliente:
                resposta = cliente.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.chave}"},
                    json=corpo,
                )
                resposta.raise_for_status()
                dados = resposta.json()
        except Exception as erro:
            raise ProvedorIndisponivel(f"Groq falhou: {erro}") from erro

        texto = (dados.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not texto.strip():
            raise ProvedorIndisponivel("Groq devolveu resposta vazia")
        return texto.strip()


class Gemini:
    nome = "gemini"

    def __init__(self) -> None:
        self.chave = os.getenv("GEMINI_API_KEY", "").strip()
        self.modelo = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

    def disponivel(self) -> bool:
        return bool(self.chave)

    def gerar(self, sistema: str, usuario: str) -> str:
        if not self.chave:
            raise ProvedorIndisponivel("GEMINI_API_KEY ausente")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.modelo}:generateContent"
        )
        corpo = {
            "systemInstruction": {"parts": [{"text": sistema}]},
            "contents": [{"role": "user", "parts": [{"text": usuario}]}],
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": 1400},
        }
        try:
            with httpx.Client(timeout=TEMPO_LIMITE) as cliente:
                resposta = cliente.post(
                    url, headers={"x-goog-api-key": self.chave}, json=corpo
                )
                resposta.raise_for_status()
                dados = resposta.json()
        except Exception as erro:
            raise ProvedorIndisponivel(f"Gemini falhou: {erro}") from erro

        candidatos = dados.get("candidates") or []
        partes = (candidatos[0].get("content", {}).get("parts") if candidatos else []) or []
        texto = "\n".join(p.get("text", "") for p in partes).strip()
        if not texto:
            raise ProvedorIndisponivel("Gemini devolveu resposta vazia")
        return texto
