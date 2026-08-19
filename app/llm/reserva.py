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


# Modelos que existem para outra finalidade e não servem para conversar.
_NAO_CONVERSACIONAIS = ("guard", "whisper", "tts", "embed", "safeguard")

# Preferência quando for preciso descobrir um modelo. O que não estiver aqui
# entra depois, ordenado pela janela de contexto.
_PREFERENCIA_GROQ = (
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "groq/compound",
)


class Groq:
    nome = "groq"

    def __init__(self) -> None:
        self.chave = os.getenv("GROQ_API_KEY", "").strip()
        self.modelo = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
        self.url = "https://api.groq.com/openai/v1/chat/completions"
        self.url_modelos = "https://api.groq.com/openai/v1/models"

    def disponivel(self) -> bool:
        return bool(self.chave)

    def _descobrir_modelo(self) -> str | None:
        """Pergunta à API quais modelos a conta tem ativos e escolhe um.

        A Groq aposenta modelos com frequência, e a chamada passa a devolver
        404. Sem isto, um nome fixo no código ou numa variável de ambiente
        transforma a aposentadoria de um modelo em queda da aplicação — que foi
        exatamente o que aconteceu em produção.
        """
        try:
            with httpx.Client(timeout=TEMPO_LIMITE) as cliente:
                resposta = cliente.get(
                    self.url_modelos, headers={"Authorization": f"Bearer {self.chave}"}
                )
                resposta.raise_for_status()
                dados = resposta.json()
        except Exception as erro:
            log.warning("não foi possível listar modelos da Groq: %s", erro)
            return None

        candidatos = [
            m
            for m in dados.get("data", [])
            if m.get("active", True)
            and not any(t in m.get("id", "").lower() for t in _NAO_CONVERSACIONAIS)
            and (m.get("context_window") or 0) >= 8192
        ]
        if not candidatos:
            return None

        por_id = {m["id"]: m for m in candidatos}
        for preferido in _PREFERENCIA_GROQ:
            if preferido in por_id:
                return preferido
        return max(candidatos, key=lambda m: m.get("context_window") or 0)["id"]

    def _pedir(self, modelo: str, sistema: str, usuario: str) -> dict:
        corpo = {
            "model": modelo,
            "temperature": 0.35,
            "max_tokens": 1400,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
        }
        return _postar_com_retry(
            self.url, {"Authorization": f"Bearer {self.chave}"}, corpo
        )

    def gerar(self, sistema: str, usuario: str) -> str:
        if not self.chave:
            raise ProvedorIndisponivel("GROQ_API_KEY ausente")

        try:
            dados = self._pedir(self.modelo, sistema, usuario)
        except ProvedorIndisponivel as erro:
            if "404" not in str(erro):
                raise ProvedorIndisponivel(f"Groq falhou: {erro}") from erro

            # 404 aqui quer dizer "esse modelo não existe (mais)". Descobrir um
            # ativo e repetir é melhor do que devolver erro para a cliente.
            substituto = self._descobrir_modelo()
            if not substituto or substituto == self.modelo:
                raise ProvedorIndisponivel(
                    f"Groq falhou: modelo {self.modelo!r} não existe e não achei "
                    f"substituto ({erro})"
                ) from erro

            log.warning(
                "modelo %r indisponível na Groq; passando a usar %r",
                self.modelo, substituto,
            )
            self.modelo = substituto
            try:
                dados = self._pedir(self.modelo, sistema, usuario)
            except ProvedorIndisponivel as erro_novo:
                raise ProvedorIndisponivel(f"Groq falhou: {erro_novo}") from erro_novo

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
