"""API HTTP da Aurora (FastAPI).

Endpoints:
    GET  /                 interface de chat
    POST /api/perguntar    pergunta -> resposta ancorada nos documentos
    GET  /api/exemplos     perguntas sugeridas
    GET  /api/documentos   estatisticas dos documentos indexados
    GET  /api/saude        health check + status dos provedores de LLM
    GET  /docs             documentacao interativa (Swagger)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .agente import PERGUNTAS_EXEMPLO, AgenteAurora
from .indice import obter_indice
from .ingestao import resumo_fontes
from .llm import Roteador

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("aurora")

RAIZ = Path(__file__).resolve().parent.parent
PASTA_WEB = RAIZ / "web"

agente: AgenteAurora | None = None


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Indexa os documentos na subida: a primeira pergunta já chega rápida."""
    global agente
    indice = obter_indice()
    agente = AgenteAurora(indice=indice)
    log.info(
        "Aurora pronta — %d trechos indexados de %s",
        indice.total,
        ", ".join(resumo_fontes()["por_documento"]),
    )
    yield
    log.info("Aurora encerrada")


app = FastAPI(
    title="Aurora — Agente de Atendimento Lumina Beauty",
    description=(
        "Agente inteligente que responde perguntas sobre produtos, ingredientes "
        "e políticas de um e-commerce de beleza, sempre ancorado em documentos "
        "PDF e CSV. Desafio Alura Agente — Oracle Next Education."
    ),
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ORIGENS_PERMITIDAS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class TurnoConversa(BaseModel):
    papel: str = Field(description="'cliente' ou 'aurora'")
    texto: str


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000, description="Pergunta da cliente")
    historico: list[TurnoConversa] = Field(
        default_factory=list, description="Turnos anteriores da conversa"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pergunta": "Posso usar retinol e ácido glicólico na mesma noite?",
                    "historico": [],
                }
            ]
        }
    }


@app.get("/", include_in_schema=False)
def pagina_inicial():
    arquivo = PASTA_WEB / "index.html"
    if arquivo.exists():
        return FileResponse(arquivo)
    return JSONResponse({"mensagem": "Aurora está no ar. Veja /docs."})


@app.post("/api/perguntar")
def perguntar(entrada: Pergunta):
    """Responde uma pergunta com base nos documentos indexados."""
    assistente = agente or AgenteAurora()
    historico = [t.model_dump() for t in entrada.historico]
    resposta = assistente.responder(entrada.pergunta, historico=historico)
    return resposta.como_dicionario()


@app.get("/api/exemplos")
def exemplos():
    """Perguntas que o agente sabe responder."""
    return {"exemplos": PERGUNTAS_EXEMPLO}


@app.get("/api/documentos")
def documentos():
    """Quais documentos foram lidos e quantos trechos cada um gerou."""
    return resumo_fontes()


@app.get("/api/saude")
def saude():
    """Health check para o balanceador e para conferir a configuração do LLM."""
    indice = obter_indice()
    return {
        "estado": "ok",
        "trechos_indexados": indice.total,
        "documentos": resumo_fontes()["por_documento"],
        "provedores_llm": Roteador().status(),
    }
