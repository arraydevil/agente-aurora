"""Gera o PDF de politicas da Lumina Beauty a partir do markdown-fonte.

O PDF em `dados/politicas_lumina.pdf` e um dos documentos que o agente le.
Mantemos o markdown em `docs_fonte/` como original editavel e versionado, e o
PDF como artefato de saida — assim o repositorio mostra a origem do documento
em vez de um binario caido do ceu.

Uso:
    python scripts/gerar_pdf.py
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "docs_fonte" / "politicas_lumina.md"
SAIDA = RAIZ / "dados" / "politicas_lumina.pdf"

ROXO = colors.HexColor("#6B4E9B")
GRAFITE = colors.HexColor("#2B2B33")
LILAS = colors.HexColor("#EDE7F6")


def estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=base["Title"], fontSize=22, textColor=ROXO,
            spaceAfter=14, leading=26,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading1"], fontSize=15, textColor=ROXO,
            spaceBefore=18, spaceAfter=8, leading=19,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading2"], fontSize=12, textColor=GRAFITE,
            spaceBefore=12, spaceAfter=6, leading=15,
        ),
        "corpo": ParagraphStyle(
            "corpo", parent=base["BodyText"], fontSize=9.5, leading=14,
            alignment=TA_JUSTIFY, spaceAfter=6, textColor=GRAFITE,
        ),
        "item": ParagraphStyle(
            "item", parent=base["BodyText"], fontSize=9.5, leading=14,
            leftIndent=14, bulletIndent=4, spaceAfter=3, textColor=GRAFITE,
        ),
        "celula": ParagraphStyle(
            "celula", parent=base["BodyText"], fontSize=8.5, leading=11,
            textColor=GRAFITE,
        ),
        "celula_cab": ParagraphStyle(
            "celula_cab", parent=base["BodyText"], fontSize=8.5, leading=11,
            textColor=colors.white, fontName="Helvetica-Bold",
        ),
    }


def marcar(texto: str) -> str:
    """Converte a marcacao inline do markdown para as tags que o reportlab aceita."""
    texto = texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    texto = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", texto)
    texto = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", texto)
    return texto


def eh_linha_tabela(linha: str) -> bool:
    return linha.startswith("|") and linha.endswith("|")


def eh_separador_tabela(linha: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:\-|]+\|", linha))


def montar_tabela(linhas: list[str], est: dict[str, ParagraphStyle]) -> Table:
    matriz: list[list[Paragraph]] = []
    for indice, linha in enumerate(linhas):
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        estilo = est["celula_cab"] if indice == 0 else est["celula"]
        matriz.append([Paragraph(marcar(c), estilo) for c in celulas])

    largura_util = A4[0] - 4 * cm
    colunas = len(matriz[0])
    tabela = Table(matriz, colWidths=[largura_util / colunas] * colunas, hAlign="LEFT")
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ROXO),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LILAS]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9BCE0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return tabela


def converter(markdown: str) -> list:
    est = estilos()
    fluxo: list = []
    buffer_tabela: list[str] = []

    def descarregar_tabela() -> None:
        if buffer_tabela:
            fluxo.append(Spacer(1, 4))
            fluxo.append(montar_tabela(buffer_tabela, est))
            fluxo.append(Spacer(1, 8))
            buffer_tabela.clear()

    for linha_bruta in markdown.splitlines():
        linha = linha_bruta.rstrip()

        if eh_linha_tabela(linha):
            if not eh_separador_tabela(linha):
                buffer_tabela.append(linha)
            continue
        descarregar_tabela()

        if not linha.strip():
            continue

        if linha.startswith("# "):
            fluxo.append(Paragraph(marcar(linha[2:]), est["titulo"]))
        elif linha.startswith("## "):
            fluxo.append(Paragraph(marcar(linha[3:]), est["h2"]))
        elif linha.startswith("### "):
            fluxo.append(Paragraph(marcar(linha[4:]), est["h3"]))
        elif linha.startswith("---"):
            fluxo.append(Spacer(1, 6))
            fluxo.append(HRFlowable(width="100%", thickness=0.6, color=ROXO))
            fluxo.append(Spacer(1, 6))
        elif re.match(r"^\s*[-*]\s+", linha):
            texto = re.sub(r"^\s*[-*]\s+", "", linha)
            fluxo.append(Paragraph(marcar(texto), est["item"], bulletText="•"))
        elif re.match(r"^\s*\d+\.\s+", linha):
            numero, _, resto = linha.strip().partition(". ")
            fluxo.append(Paragraph(marcar(resto), est["item"], bulletText=f"{numero}."))
        else:
            fluxo.append(Paragraph(marcar(linha), est["corpo"]))

    descarregar_tabela()
    return fluxo


def rodape(canvas, documento) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#7A7A88"))
    canvas.drawString(2 * cm, 1.2 * cm, "Lumina Beauty — Manual de Atendimento v3.1")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {documento.page}")
    canvas.restoreState()


def main() -> None:
    markdown = ENTRADA.read_text(encoding="utf-8")
    documento = SimpleDocTemplate(
        str(SAIDA),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Manual de Atendimento — Lumina Beauty",
        author="Lumina Beauty",
        subject="Políticas, FAQ e guia de ativos",
    )
    documento.build(converter(markdown), onFirstPage=rodape, onLaterPages=rodape)
    tamanho = SAIDA.stat().st_size / 1024
    print(f"PDF gerado: {SAIDA.relative_to(RAIZ)} ({tamanho:.0f} KB)")


if __name__ == "__main__":
    main()
