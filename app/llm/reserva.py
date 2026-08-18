"""Provedores de reserva via REST puro (sem SDK).

Entram em acao quando a OCI Generative AI nao responde: conta ainda em
verificacao, credencial ausente, limite de servico ou indisponibilidade.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from .base import ProvedorIndisponivel

log = logging.getLogger(__name__)

TEMPO_LIMITE = httpx.Timeout(60.0, connect=10.0)

TENTATIVAS = 3
ESPERA_MAXIMA = 25.0


def _postar_com_retry(url: str, cabecalhos: dict[str, str], corpo: dict) -> dict:
    """POST com repetição em 429 e 5xx.

    O nível gratuito dos provedores limita tokens por minuto, e este agente manda
    prompts grandes (seis trechos de documento por pergunta). Sem repetição, uma
    rajada de perguntas — exatamente o que acontece ao gerar os exemplos ou ao
    demonstrar o projeto — derruba metade das chamadas.
    """
    espera = 2.0
    ultimo_erro = ""

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            with httpx.Client(timeout=TEMPO_LIMITE) as cliente:
                resposta = cliente.post(url, headers=cabecalhos, json=corpo)

            if resposta.status_code == 429 or resposta.status_code >= 500:
                ultimo_erro = f"HTTP {resposta.status_code}"
                if tentativa == TENTATIVAS:
                    break
                # O provedor costuma dizer quanto esperar; respeitamos o valor dele.
                cabecalho_espera = resposta.headers.get("retry-after")
                try:
                    pausa = float(cabecalho_espera) if cabecalho_espera else espera
                except ValueError:
                    pausa = espera
                pausa = min(pausa, ESPERA_MAXIMA)
                log.info(
                    "%s em %s — repetindo em %.1fs (tentativa %d/%d)",
                    ultimo_erro, url, pausa, tentativa, TENTATIVAS,
                )
                time.sleep(pausa)
                espera *= 2
                continue

            resposta.raise_for_status()
            return resposta.json()

        except httpx.HTTPStatusError as erro:
            raise ProvedorIndisponivel(str(erro)) from erro
        except Exception as erro:
            ultimo_erro = str(erro)
            if tentativa == TENTATIVAS:
                break
            time.sleep(espera)
            espera *= 2

    raise ProvedorIndisponivel(f"esgotadas {TENTATIVAS} tentativas — {ultimo_erro}")


class Groq:
    nome = "groq"

    def __init__(self) -> None:
        self.chave = os.getenv("GROQ_API_KEY", "").strip()
        self.modelo = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
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
            dados = _postar_com_retry(
                self.url, {"Authorization": f"Bearer {self.chave}"}, corpo
            )
        except ProvedorIndisponivel as erro:
            raise ProvedorIndisponivel(f"Groq falhou: {erro}") from erro

        texto = (dados.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not texto.strip():
            raise ProvedorIndisponivel("Groq devolveu resposta vazia")
        return texto.strip()


class Gemini:
    nome = "gemini"

    def __init__(self) -> None:
        self.chave = os.getenv("GEMINI_API_KEY", "").strip()
        self.modelo = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

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
            dados = _postar_com_retry(url, {"x-goog-api-key": self.chave}, corpo)
        except ProvedorIndisponivel as erro:
            raise ProvedorIndisponivel(f"Gemini falhou: {erro}") from erro

        candidatos = dados.get("candidates") or []
        partes = (candidatos[0].get("content", {}).get("parts") if candidatos else []) or []
        texto = "\n".join(p.get("text", "") for p in partes).strip()
        if not texto:
            raise ProvedorIndisponivel("Gemini devolveu resposta vazia")
        return texto
