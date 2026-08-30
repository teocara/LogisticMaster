"""Genera la demo statica incorporando lo scenario nel template."""
from __future__ import annotations

import json
import os
import subprocess
import sys

CARTELLA = os.path.dirname(os.path.abspath(__file__))


def costruisci() -> str:
    subprocess.run([sys.executable, os.path.join(CARTELLA, "genera_dati.py")], check=True)
    with open(os.path.join(CARTELLA, "dati.json"), encoding="utf-8") as file:
        dati = file.read()
    with open(os.path.join(CARTELLA, "template.html"), encoding="utf-8") as file:
        pagina = file.read()

    # Il JSON viene incorporato in un tag <script type="application/json">:
    # va neutralizzata solo la sequenza che chiuderebbe il tag.
    json.loads(dati)
    pagina = pagina.replace("__DATI_JSON__", dati.replace("</", "<\\/"))

    destinazione = os.path.join(CARTELLA, "logisticmaster-demo.html")
    with open(destinazione, "w", encoding="utf-8") as file:
        file.write(pagina)
    return destinazione


if __name__ == "__main__":
    percorso = costruisci()
    print(f"{percorso}: {os.path.getsize(percorso) / 1024:.0f} KB")
