"""API del cruscotto direzionale: indicatori di rete, servizio e costo."""
from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter

from .. import db
from ..core import pianificazione as motore

router = APIRouter(prefix="/api/kpi", tags=["kpi"])


@router.get("/cruscotto")
def cruscotto() -> dict:
    """Sintesi dello stato della rete per la direzione operations."""
    siti = db.query("SELECT tipo, COUNT(*) AS n FROM siti WHERE attivo = 1 GROUP BY tipo")
    ordini = db.query("SELECT stato, COUNT(*) AS n FROM ordini GROUP BY stato")
    valore = db.query_uno(
        """SELECT SUM(g.quantita * a.valore_unitario) AS valore,
                  SUM(g.quantita) AS pezzi
           FROM giacenze g JOIN articoli a ON a.id = g.articolo_id"""
    )
    analisi = motore.analisi_scorte()
    righe = analisi["righe"]
    rotture = [r for r in righe if r["copertura_giorni"] < r["lead_time_giorni"]]
    per_sito: dict[str, dict] = defaultdict(lambda: {"valore": 0.0, "criticita": 0})
    for r in righe:
        per_sito[r["sito_nome"]]["valore"] += r["valore_giacenza"]
        if r["sotto_riordino"]:
            per_sito[r["sito_nome"]]["criticita"] += 1

    ultimo = db.query_uno("SELECT risultato FROM piani ORDER BY id DESC LIMIT 1")
    kpi_ultimo_piano = json.loads(ultimo["risultato"])["kpi"] if ultimo else {}

    return {
        "rete": {s["tipo"]: s["n"] for s in siti},
        "ordini": {o["stato"]: o["n"] for o in ordini},
        "magazzino": {
            "valore_giacenze_eur": round(valore["valore"] or 0, 2),
            "pezzi_a_stock": round(valore["pezzi"] or 0, 0),
            "coppie_sito_articolo": len(righe),
            "sotto_punto_riordino": analisi["sotto_riordino"],
            "rischio_rottura": len(rotture),
            "copertura_media_giorni": round(
                sum(r["copertura_giorni"] for r in righe) / len(righe), 1
            )
            if righe
            else 0.0,
        },
        "per_sito": [
            {"sito": nome, "valore_giacenze_eur": round(v["valore"], 2), "criticita": v["criticita"]}
            for nome, v in sorted(per_sito.items(), key=lambda x: -x[1]["valore"])
        ],
        "criticita_top": [
            {
                "sito": r["sito_nome"],
                "articolo": r["articolo_codice"],
                "descrizione": r["articolo_descrizione"],
                "copertura_giorni": r["copertura_giorni"],
                "lead_time_giorni": r["lead_time_giorni"],
                "disponibile": r["disponibile"],
                "punto_riordino": r["punto_riordino"],
            }
            for r in righe[:12]
        ],
        "ultimo_piano": kpi_ultimo_piano,
    }


@router.get("/serie-storica")
def serie_storica(limite: int = 20) -> list[dict]:
    """Andamento dei KPI dei piani salvati, dal piu' recente."""
    piani = db.query(
        "SELECT id, creato_il, data_riferimento, descrizione, risultato FROM piani ORDER BY id DESC LIMIT ?",
        (limite,),
    )
    serie = []
    for p in piani:
        risultato = json.loads(p["risultato"])
        kpi = risultato.get("kpi", {})
        confronto = risultato.get("confronto", {})
        serie.append(
            {
                "piano_id": p["id"],
                "creato_il": p["creato_il"],
                "data_riferimento": p["data_riferimento"],
                "descrizione": p["descrizione"],
                "km_totali": kpi.get("km_totali", 0),
                "costo_totale_eur": kpi.get("costo_totale_eur", 0),
                "costo_per_km": kpi.get("costo_per_km", 0),
                "saturazione_media_pct": kpi.get("saturazione_media_pct", 0),
                "co2_kg": kpi.get("co2_kg", 0),
                "risparmio_pct": confronto.get("costo_risparmiato_pct", 0),
            }
        )
    return list(reversed(serie))
