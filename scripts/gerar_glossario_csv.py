"""Converte a base curada de ingredientes (JSON) no CSV usado pelo agente.

O CSV e um dos documentos-fonte oficiais do projeto: e ele que o pipeline de
ingestao le em `app/ingestao.py`. O JSON permanece no repositorio como fonte
editavel, com as regras de incompatibilidade que alimentam o guia em PDF.

Uso:
    python scripts/gerar_glossario_csv.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "dados" / "base_ingredientes.json"
SAIDA = RAIZ / "dados" / "glossario_ingredientes.csv"

COLUNAS = [
    "inci",
    "nome_popular",
    "sinonimos",
    "categoria",
    "funcao",
    "comedogenicidade",
    "tipos_de_pele",
    "evitar_em",
    "alertas",
    "nivel_de_atencao",
]


def main() -> None:
    dados = json.loads(ENTRADA.read_text(encoding="utf-8"))
    ingredientes = dados["ingredientes"]

    with SAIDA.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS)
        escritor.writeheader()
        for item in ingredientes:
            escritor.writerow(
                {
                    "inci": item["inci"],
                    "nome_popular": item.get("pt", ""),
                    "sinonimos": ";".join(item.get("sin", [])),
                    "categoria": item["cat"],
                    "funcao": item["fun"],
                    "comedogenicidade": item.get("com", ""),
                    "tipos_de_pele": ";".join(item.get("peles", [])),
                    "evitar_em": ";".join(item.get("evitar", [])),
                    "alertas": ";".join(item.get("alertas", [])),
                    "nivel_de_atencao": item["nivel"],
                }
            )

    print(f"{len(ingredientes)} ingredientes gravados em {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
