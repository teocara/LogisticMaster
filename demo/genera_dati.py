"""Estrae dal motore uno scenario completo per la demo statica offline.

La demo (``demo/logisticmaster-demo.html``) e' una copia navigabile
dell'interfaccia che non richiede il server: i dati vengono calcolati qui
una volta sola e incorporati nella pagina.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, seed  # noqa: E402
from app.api import anagrafiche, kpi, pianificazione  # noqa: E402
from app.core.costi import PROFILI_VEICOLO  # noqa: E402
from app.core.geo import MatriceDistanze, Punto  # noqa: E402
from app.models import ParametriPianoInput  # noqa: E402


def genera() -> dict:
    # Lo scenario viene sempre ricaricato: la demo deve essere riproducibile
    # e gli ordini devono risultare ancora da pianificare.
    seed.popola()

    siti = anagrafiche.elenco_siti()
    matrice = MatriceDistanze([Punto(s["id"], s["lat"], s["lon"]) for s in siti])

    # Matrice completa fra tutti i siti: serve al simulatore della demo,
    # che ricalcola i costi in pagina senza chiamare le API.
    tratte = {}
    for a in siti:
        for b in siti:
            if a["id"] == b["id"]:
                continue
            traghetto = matrice.traghetto(a["id"], b["id"])
            tratte[f"{a['id']}-{b['id']}"] = {
                "km": matrice.km(a["id"], b["id"]),
                "ore": round(matrice.ore_guida(a["id"], b["id"]), 3),
                "traghetto": {"tratta": traghetto["tratta"], "ore": traghetto["ore"], "costo_eur": traghetto["costo_eur"]}
                if traghetto
                else None,
            }

    piano = pianificazione.genera_piano(ParametriPianoInput(salva=False, descrizione="Piano dimostrativo"))

    return {
        "stato": {"conteggi": {k: v for k, v in _conteggi().items()}},
        "siti": siti,
        "profili": anagrafiche.elenco_profili(),
        "veicoli": anagrafiche.elenco_veicoli(),
        "vettori": anagrafiche.elenco_vettori(),
        "cruscotto": kpi.cruscotto(),
        "scorte": pianificazione.analisi_scorte(solo_critiche=False, limite=2000),
        "trasferimenti": pianificazione.trasferimenti(km_massimi=900.0),
        "ordini": anagrafiche.elenco_ordini(limite=1000),
        "matrice_rete": pianificazione.matrice_rete(),
        "tratte": tratte,
        "piano": piano,
        "parametri_costo": {
            "profili": {
                p.codice: {
                    "descrizione": p.descrizione,
                    "portata_kg": p.portata_kg,
                    "volume_m3": p.volume_m3,
                    "posti_pallet": p.posti_pallet,
                    "consumo_km_litro": p.consumo_km_litro,
                    "pedaggio_eur_km": p.pedaggio_eur_km,
                    "manutenzione_eur_km": p.manutenzione_eur_km,
                    "costo_fisso_giorno": p.costo_fisso_giorno,
                    "costo_autista_ora": p.costo_autista_ora,
                }
                for p in PROFILI_VEICOLO.values()
            }
        },
    }


def _conteggi() -> dict:
    return {
        tabella: db.query_uno(f"SELECT COUNT(*) AS n FROM {tabella}")["n"]
        for tabella in ("siti", "articoli", "giacenze", "ordini", "veicoli", "vettori")
    }


if __name__ == "__main__":
    dati = genera()
    destinazione = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dati.json")
    with open(destinazione, "w", encoding="utf-8") as file:
        json.dump(dati, file, ensure_ascii=False, separators=(",", ":"))
    print(f"{destinazione}: {os.path.getsize(destinazione) / 1024:.0f} KB")
