"""Roda as perguntas de exemplo e grava as respostas reais em docs/exemplos_respostas.md.

O desafio pede "exemplos de respostas geradas pelo agente" no README. Em vez de
colar respostas escritas a mao, este script executa o agente de verdade e grava
a saida, com o provedor que respondeu e as fontes citadas. Rode de novo sempre
que mudar a base ou o prompt.

Uso:
    python scripts/gerar_exemplos.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PAUSA_ENTRE_PERGUNTAS = 8.0

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ / ".env")

from app.agente import PERGUNTAS_EXEMPLO, AgenteAurora  # noqa: E402
from app.ingestao import resumo_fontes  # noqa: E402

SAIDA = RAIZ / "docs" / "exemplos_respostas.md"


def main() -> None:
    agente = AgenteAurora()
    resumo = resumo_fontes()

    linhas = [
        "# Exemplos de respostas geradas pela Aurora",
        "",
        f"Gerado automaticamente por `scripts/gerar_exemplos.py` em "
        f"{datetime.now().strftime('%d/%m/%Y às %H:%M')}.",
        "",
        f"Base indexada no momento da geração: **{resumo['total_trechos']} trechos** "
        f"de {len(resumo['por_documento'])} documentos "
        f"({', '.join(f'`{k}`' for k in resumo['por_documento'])}).",
        "",
        "---",
        "",
    ]

    for numero, pergunta in enumerate(PERGUNTAS_EXEMPLO, start=1):
        print(f"[{numero}/{len(PERGUNTAS_EXEMPLO)}] {pergunta}")
        if numero > 1:
            # Espaça as chamadas para não estourar o limite por minuto do nível
            # gratuito. O provedor já repete em 429; isto evita chegar lá.
            time.sleep(PAUSA_ENTRE_PERGUNTAS)
        resposta = agente.responder(pergunta)

        linhas.append(f"## {numero}. {pergunta}")
        linhas.append("")
        linhas.append(resposta.resposta)
        linhas.append("")
        linhas.append(
            f"<sub>Provedor: `{resposta.provedor}` · "
            f"{resposta.trechos_recuperados} trechos recuperados · "
            f"{resposta.tempo_ms} ms</sub>"
        )
        linhas.append("")
        if resposta.fontes:
            linhas.append("<details><summary>Trechos consultados</summary>")
            linhas.append("")
            for fonte in resposta.fontes:
                linhas.append(
                    f"- `{fonte.documento}` — {fonte.referencia} "
                    f"(relevância {fonte.pontuacao})"
                )
            linhas.append("")
            linhas.append("</details>")
            linhas.append("")
        linhas.append("---")
        linhas.append("")

    SAIDA.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\n{len(PERGUNTAS_EXEMPLO)} exemplos gravados em {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
