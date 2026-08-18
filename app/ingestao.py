"""Leitura e processamento dos documentos-fonte do agente.

Tres documentos alimentam a Aurora, e cada um exige um tratamento diferente:

  dados/politicas_lumina.pdf        PDF  -> texto por pagina, quebrado por secao
  dados/catalogo_produtos.csv       CSV  -> uma ficha de produto por linha
  dados/glossario_ingredientes.csv  CSV  -> uma ficha de ingrediente por linha

Os dois CSVs nao viram texto cru: cada linha e reescrita como frase legivel,
porque o buscador e o LLM trabalham muito melhor com "Preco: R$ 89,90" do que
com uma tupla solta. E o que transforma dado tabular em conhecimento recuperavel.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "dados"

ARQUIVO_PDF = PASTA_DADOS / "politicas_lumina.pdf"
ARQUIVO_CATALOGO = PASTA_DADOS / "catalogo_produtos.csv"
ARQUIVO_GLOSSARIO = PASTA_DADOS / "glossario_ingredientes.csv"

TAMANHO_MAXIMO_TRECHO = 1200
SOBREPOSICAO = 150

# "3.4 Reacao alergica", "7.1 Combinacoes que exigem cuidado"
PADRAO_SECAO = re.compile(r"^\d+(?:\.\d+)?\s+[A-ZÀ-ÿ]")
PADRAO_RODAPE = re.compile(r"^(Lumina Beauty — Manual|Página \d+)")


@dataclass
class Trecho:
    """Unidade recuperavel de conhecimento, sempre rastreavel ate a origem."""

    identificador: str
    texto: str
    fonte: str
    tipo: str  # pdf | csv
    referencia: str
    metadados: dict[str, Any] = field(default_factory=dict)

    def citacao(self) -> str:
        return f"{self.fonte} — {self.referencia}"


# --------------------------------------------------------------------- PDF


def _limpar_linhas_pdf(texto: str) -> list[str]:
    linhas = []
    for linha in texto.splitlines():
        limpa = linha.strip()
        if not limpa or PADRAO_RODAPE.match(limpa):
            continue
        linhas.append(limpa)
    return linhas


def _fatiar(texto: str, limite: int, sobreposicao: int) -> list[str]:
    """Divide um bloco longo respeitando fronteira de frase sempre que possivel."""
    if len(texto) <= limite:
        return [texto]

    pedacos: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + limite, len(texto))
        if fim < len(texto):
            corte = texto.rfind(". ", inicio + limite // 2, fim)
            if corte != -1:
                fim = corte + 1
        pedacos.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = max(fim - sobreposicao, inicio + 1)
    return [p for p in pedacos if p]


def carregar_pdf(caminho: Path = ARQUIVO_PDF) -> list[Trecho]:
    """Le o PDF e quebra o conteudo em secoes numeradas, guardando a pagina."""
    try:
        from pypdf import PdfReader
    except ImportError as erro:  # pragma: no cover
        raise RuntimeError("pacote `pypdf` nao instalado") from erro

    leitor = PdfReader(str(caminho))
    fonte = caminho.name

    secoes: list[dict[str, Any]] = []
    atual: dict[str, Any] | None = None

    for numero_pagina, pagina in enumerate(leitor.pages, start=1):
        for linha in _limpar_linhas_pdf(pagina.extract_text() or ""):
            if PADRAO_SECAO.match(linha):
                if atual:
                    secoes.append(atual)
                atual = {
                    "titulo": linha,
                    "linhas": [],
                    "pagina_inicial": numero_pagina,
                    "pagina_final": numero_pagina,
                }
                continue
            if atual is None:
                atual = {
                    "titulo": "Apresentação",
                    "linhas": [],
                    "pagina_inicial": numero_pagina,
                    "pagina_final": numero_pagina,
                }
            atual["linhas"].append(linha)
            atual["pagina_final"] = numero_pagina

    if atual:
        secoes.append(atual)

    trechos: list[Trecho] = []
    for indice, secao in enumerate(secoes):
        corpo = " ".join(secao["linhas"]).strip()
        if not corpo:
            continue
        completo = f"{secao['titulo']}\n{corpo}"
        partes = _fatiar(completo, TAMANHO_MAXIMO_TRECHO, SOBREPOSICAO)
        for sufixo, parte in enumerate(partes, start=1):
            paginas = (
                f"p. {secao['pagina_inicial']}"
                if secao["pagina_inicial"] == secao["pagina_final"]
                else f"p. {secao['pagina_inicial']}-{secao['pagina_final']}"
            )
            referencia = f"seção {secao['titulo'][:60]}, {paginas}"
            if len(partes) > 1:
                referencia += f" ({sufixo}/{len(partes)})"
            trechos.append(
                Trecho(
                    identificador=f"pdf-{indice:03d}-{sufixo}",
                    texto=parte,
                    fonte=fonte,
                    tipo="pdf",
                    referencia=referencia,
                    metadados={"secao": secao["titulo"], "pagina": secao["pagina_inicial"]},
                )
            )

    log.info("PDF %s: %d seções, %d trechos", fonte, len(secoes), len(trechos))
    return trechos


# --------------------------------------------------------------------- CSV


def _lista(valor: str) -> list[str]:
    return [item.strip() for item in (valor or "").split(";") if item.strip()]


def _juntar(valores: list[str]) -> str:
    return ", ".join(valores) if valores else "não informado"


def carregar_catalogo(caminho: Path = ARQUIVO_CATALOGO) -> list[Trecho]:
    """Transforma cada linha do catalogo em uma ficha de produto em texto corrido."""
    trechos: list[Trecho] = []
    fonte = caminho.name

    with caminho.open(encoding="utf-8", newline="") as arquivo:
        for numero_linha, linha in enumerate(csv.DictReader(arquivo), start=2):
            preco = float(linha["preco_brl"])
            estoque = int(linha["estoque"])
            disponibilidade = (
                "disponível em estoque" if estoque > 0 else "esgotado no momento"
            )
            # A palavra que carrega a decisão precisa ser um token próprio e
            # distintivo. "NÃO indicado" não serve: "não" é palavra vazia no
            # índice, e o trecho acabaria recuperado como se fosse liberado.
            gestante = {
                "sim": "liberado na gestação e na amamentação",
                "nao": "contraindicado na gestação e na amamentação",
                "consultar": "uso na gestação exige confirmação médica",
            }.get(linha["seguro_gestante"], "sem informação sobre gestação")

            texto = (
                f"PRODUTO {linha['codigo']} — {linha['nome']} ({linha['marca']}).\n"
                f"Categoria: {linha['categoria']} / {linha['subcategoria']}. "
                f"Apresentação: {linha['volume']}.\n"
                f"Preço: R$ {preco:.2f}".replace(".", ",")
                + f". Estoque: {estoque} unidades, {disponibilidade}. "
                f"Avaliação média: {linha['avaliacao']} de 5.\n"
                f"Indicado para pele: {_juntar(_lista(linha['tipo_pele']))}.\n"
                f"Ativos principais: {_juntar(_lista(linha['ativos_principais']))}.\n"
                f"Indicações de uso: {_juntar(_lista(linha['indicacoes']))}.\n"
                f"Gestação: {gestante}. "
                f"Vegano: {'sim' if linha['vegano'] == 'sim' else 'não'}."
            )

            trechos.append(
                Trecho(
                    identificador=f"produto-{linha['codigo']}",
                    texto=texto,
                    fonte=fonte,
                    tipo="csv",
                    referencia=f"produto {linha['codigo']}, linha {numero_linha}",
                    metadados={
                        "codigo": linha["codigo"],
                        "nome": linha["nome"],
                        "preco": preco,
                        "categoria": linha["categoria"],
                        "tipo_pele": _lista(linha["tipo_pele"]),
                        "seguro_gestante": linha["seguro_gestante"],
                        "vegano": linha["vegano"] == "sim",
                        "estoque": estoque,
                    },
                )
            )

    log.info("Catálogo %s: %d produtos", fonte, len(trechos))
    return trechos


def carregar_glossario(caminho: Path = ARQUIVO_GLOSSARIO) -> list[Trecho]:
    """Transforma cada ingrediente INCI em uma ficha tecnica em texto corrido."""
    trechos: list[Trecho] = []
    fonte = caminho.name

    rotulo_nivel = {
        "ok": "uso tranquilo para a maioria das pessoas",
        "atencao": "merece atenção",
        "cuidado": "exige cuidado redobrado",
    }

    with caminho.open(encoding="utf-8", newline="") as arquivo:
        for numero_linha, linha in enumerate(csv.DictReader(arquivo), start=2):
            sinonimos = _lista(linha["sinonimos"])
            evitar = _lista(linha["evitar_em"])
            alertas = _lista(linha["alertas"])
            comedogenicidade = linha["comedogenicidade"]

            partes = [
                f"INGREDIENTE {linha['inci']} (nome popular: {linha['nome_popular']}).",
                f"Categoria: {linha['categoria']}. Função: {linha['funcao']}",
                f"Indicado para pele: {_juntar(_lista(linha['tipos_de_pele']))}.",
                f"Nível de atenção: {rotulo_nivel.get(linha['nivel_de_atencao'], linha['nivel_de_atencao'])}.",
            ]
            if comedogenicidade not in ("", "None"):
                partes.append(
                    f"Comedogenicidade: {comedogenicidade} de 5 "
                    f"({'baixo' if int(comedogenicidade) <= 1 else 'moderado' if int(comedogenicidade) <= 2 else 'alto'} risco de obstruir poros)."
                )
            if sinonimos:
                partes.append(f"Também aparece no rótulo como: {', '.join(sinonimos)}.")
            if evitar:
                partes.append(f"Evitar em: {'; '.join(evitar)}.")
            if alertas:
                partes.append(f"Alertas: {'; '.join(alertas)}.")

            trechos.append(
                Trecho(
                    identificador=f"ingrediente-{numero_linha:03d}",
                    texto="\n".join(partes),
                    fonte=fonte,
                    tipo="csv",
                    referencia=f"ingrediente {linha['inci']}, linha {numero_linha}",
                    metadados={
                        "inci": linha["inci"],
                        "nome_popular": linha["nome_popular"],
                        "categoria": linha["categoria"],
                        "nivel": linha["nivel_de_atencao"],
                    },
                )
            )

    log.info("Glossário %s: %d ingredientes", fonte, len(trechos))
    return trechos


# ----------------------------------------------------------------- conjunto


@lru_cache(maxsize=1)
def carregar_documentos() -> tuple[Trecho, ...]:
    """Le os tres documentos-fonte uma unica vez por processo."""
    trechos: list[Trecho] = []
    trechos.extend(carregar_pdf())
    trechos.extend(carregar_catalogo())
    trechos.extend(carregar_glossario())
    return tuple(trechos)


def resumo_fontes() -> dict[str, Any]:
    """Estatisticas dos documentos carregados, exibidas em /api/saude e no README."""
    trechos = carregar_documentos()
    por_fonte: dict[str, int] = {}
    for trecho in trechos:
        por_fonte[trecho.fonte] = por_fonte.get(trecho.fonte, 0) + 1
    return {
        "total_trechos": len(trechos),
        "por_documento": por_fonte,
        "caracteres": sum(len(t.texto) for t in trechos),
    }
