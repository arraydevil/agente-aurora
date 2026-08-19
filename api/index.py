"""Ponto de entrada para o runtime Python da Vercel.

A Vercel procura um objeto ASGI chamado `app` dentro de `api/`. Este arquivo só
coloca a raiz do projeto no caminho de import e reexporta a aplicação FastAPI —
toda a lógica continua em `app/`, sem nenhuma bifurcação por plataforma.

O mesmo código roda sem alteração via Docker (`Dockerfile`) e via AWS App Runner
(`apprunner.yaml`).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.main import app  # noqa: E402

__all__ = ["app"]
