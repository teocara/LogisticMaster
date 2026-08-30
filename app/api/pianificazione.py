"""API di pianificazione: scorte, trasferimenti, piani di trasporto, simulazioni."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..core import pianificazione as motore
from ..core.costi import (
    PROFILI_VEICOLO,
    TariffaVettore,
    co2_kg,
    confronta_make_or_buy,
    durata_sosta_ore,
)
from ..core.geo import MatriceDistanze, Punto
from ..models import ParametriPianoInput, SimulazioneMakeOrBuy

router = APIRouter(prefix="/api", tags=["pianificazione"])


@router.get("/scorte/analisi")
def analisi_scorte(solo_critiche: bool = False, limite: int = Query(default=500, le=2000)) -> dict:
    """Parametri di riordino e criticita' per sito/articolo."""
    risultato = motore.analisi_scorte()
    righe = risultato["righe"]
    if solo_critiche:
        righe = [r for r in righe if r["sotto_riordino"]]
    risultato["righe"] = righe[:limite]
    risultato["mostrate"] = len(risultato["righe"])
    return risultato


@router.get("/scorte/trasferimenti")
def trasferimenti(km_massimi: float = Query(default=900.0, gt=0)) -> dict:
    """Proposte di riequilibrio della rete fra stabilimenti e depositi."""
    return motore.proposte_trasferimenti(km_massimi=km_massimi)


@router.post("/piani/genera")
def genera_piano(parametri: ParametriPianoInput) -> dict:
    """Genera il piano di trasporto: consolidamento, giri, costi, KPI."""
    if parametri.profilo_predefinito not in PROFILI_VEICOLO:
        raise HTTPException(
            422, f"Profilo veicolo sconosciuto. Ammessi: {', '.join(PROFILI_VEICOLO)}"
        )
    if parametri.data_da and parametri.data_a and parametri.data_a < parametri.data_da:
        raise HTTPException(422, "L'intervallo di date e' invertito")

    configurazione = motore.ParametriPiano(
        data_da=parametri.data_da,
        data_a=parametri.data_a,
        ora_partenza=parametri.ora_partenza,
        soglia_groupage_pct=parametri.soglia_groupage_pct,
        profilo_predefinito=parametri.profilo_predefinito,
        sconto_vettore_pct=parametri.sconto_vettore_pct,
    )
    risultato = motore.genera_piano(configurazione)
    if parametri.salva and risultato["giri"]:
        risultato["piano_id"] = motore.salva_piano(risultato, parametri.descrizione)
    return risultato


@router.get("/piani")
def elenco_piani(limite: int = Query(default=50, le=200)) -> list[dict]:
    piani = db.query(
        "SELECT id, creato_il, data_riferimento, descrizione, parametri FROM piani ORDER BY id DESC LIMIT ?",
        (limite,),
    )
    for p in piani:
        p["parametri"] = json.loads(p["parametri"]) if p["parametri"] else {}
        p["consegne"] = db.query_uno(
            "SELECT COUNT(*) AS n FROM consegne WHERE piano_id = ?", (p["id"],)
        )["n"]
    return piani


@router.get("/piani/{piano_id}")
def dettaglio_piano(piano_id: int) -> dict:
    piano = db.query_uno("SELECT * FROM piani WHERE id = ?", (piano_id,))
    if not piano:
        raise HTTPException(404, "Piano non trovato")
    piano["risultato"] = json.loads(piano["risultato"])
    piano["parametri"] = json.loads(piano["parametri"]) if piano["parametri"] else {}
    return piano


@router.post("/simulazioni/make-or-buy")
def simulazione_make_or_buy(dati: SimulazioneMakeOrBuy) -> dict:
    """Confronta flotta propria e vettore terzo su una singola relazione."""
    if dati.profilo not in PROFILI_VEICOLO:
        raise HTTPException(422, f"Profilo veicolo sconosciuto: {dati.profilo}")
    siti = motore.carica_siti()
    for sito_id in (dati.origine_id, dati.destino_id):
        if sito_id not in siti:
            raise HTTPException(404, f"Sito inesistente: {sito_id}")

    matrice = MatriceDistanze(
        [Punto(s["id"], s["lat"], s["lon"]) for s in (siti[dati.origine_id], siti[dati.destino_id])]
    )
    km_tratta = matrice.km(dati.origine_id, dati.destino_id)
    ore_tratta = matrice.ore_guida(dati.origine_id, dati.destino_id)
    traghetto = matrice.traghetto(dati.origine_id, dati.destino_id)
    moltiplicatore = 2 if dati.andata_ritorno else 1
    profilo = PROFILI_VEICOLO[dati.profilo]

    confronto = confronta_make_or_buy(
        profilo=profilo,
        km=km_tratta * moltiplicatore,
        ore_guida=ore_tratta * moltiplicatore,
        ore_sosta=durata_sosta_ore(dati.pallet),
        peso_kg=dati.peso_kg,
        volume_m3=dati.volume_m3,
        tariffa=TariffaVettore(nome="Vettore convenzionato", sconto_pct=dati.sconto_vettore_pct),
        costo_traghetti=(traghetto["costo_eur"] * moltiplicatore) if traghetto else 0.0,
        isole=bool(traghetto),
    )
    confronto.update(
        {
            "origine": siti[dati.origine_id]["nome"],
            "destino": siti[dati.destino_id]["nome"],
            "km_tratta": km_tratta,
            "km_totali": round(km_tratta * moltiplicatore, 1),
            "ore_guida": round(ore_tratta * moltiplicatore, 2),
            "traghetto": traghetto["tratta"] if traghetto else None,
            "ore_traghetto": round(traghetto["ore"] * moltiplicatore, 2) if traghetto else 0.0,
            "veicolo": profilo.descrizione,
            "co2_kg": co2_kg(profilo, km_tratta * moltiplicatore),
            "saturazione_peso_pct": round(dati.peso_kg / profilo.portata_kg * 100, 1),
            "saturazione_volume_pct": round(dati.volume_m3 / profilo.volume_m3 * 100, 1),
        }
    )
    return confronto


@router.get("/rete/matrice")
def matrice_rete() -> dict:
    """Matrice delle distanze e dei tempi fra i siti interni della rete."""
    siti = [
        s
        for s in motore.carica_siti().values()
        if s["tipo"] in ("STABILIMENTO", "DEPOSITO", "CROSSDOCK")
    ]
    matrice = MatriceDistanze([Punto(s["id"], s["lat"], s["lon"]) for s in siti])
    return {
        "siti": [
            {"id": s["id"], "codice": s["codice"], "nome": s["nome"], "tipo": s["tipo"]}
            for s in siti
        ],
        "km": [[matrice.km(a["id"], b["id"]) for b in siti] for a in siti],
        "ore": [[round(matrice.ore(a["id"], b["id"]), 2) for b in siti] for a in siti],
    }
