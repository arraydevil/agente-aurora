# Imagem única, usada igual na máquina local e na VM da OCI.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências primeiro: aproveita o cache de camada quando só o código muda.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY dados/ ./dados/
COPY web/ ./web/
COPY scripts/ ./scripts/
COPY docs_fonte/ ./docs_fonte/

# Usuário sem privilégios: o container não precisa de root para servir HTTP.
RUN useradd --create-home --uid 1000 aurora && chown -R aurora:aurora /app
USER aurora

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8000')}/api/saude\").read()"

# Forma shell para expandir ${PORT}: App Runner, Lightsail e afins injetam a
# porta por variável de ambiente em vez de fixá-la na imagem.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
