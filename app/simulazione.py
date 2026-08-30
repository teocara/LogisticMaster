"""Simulatore di esecuzione: genera consuntivi realistici per la demo.

Non fa parte della logica di pianificazione: serve a popolare la
piattaforma con viaggi eseguiti, esiti di consegna e scostamenti di
costo, cosi' che il cruscotto OTIF abbia dati su cui essere valutato
prima dell'innesto sul gestionale aziendale.

Le deviazioni sono estratte con distribuzioni calibrate su un servizio
manifatturiero italiano di buon livello: circa il 90% delle consegne
puntuali e il 94% complete, con le cause distribuite come si osservano
sul campo (traffico e attese allo scarico davanti a tutte).
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from . import db
from .core import esecuzione

# Probabilita' delle deviazioni per singola tappa.
PROB_RITARDO_LIEVE = 0.16      # entro l'ora, tipicamente traffico o attesa
PROB_RITARDO_GRAVE = 0.05      # oltre l'ora, spesso slitta la finestra
PROB_RINVIO_GIORNO = 0.022     # consegna rimandata al giorno successivo
PROB_PARZIALE = 0.055          # merce non disponibile alla partenza
PROB_NON_ESEGUITA = 0.012      # destinatario chiuso o merce rifiutata

CAUSALI_RITARDO = ["TRAFFICO", "TRAFFICO", "ATTESA_SCARICO", "METEO", "GUASTO"]
CAUSALI_RINVIO = ["GUASTO", "SITO_CHIUSO", "TRAFFICO"]
CAUSALI_PARZIALE = ["MERCE_MANCANTE", "MERCE_MANCANTE", "DOCUMENTI"]
CAUSALI_RIFIUTO = ["SITO_CHIUSO", "DOCUMENTI", "ALTRO"]


def _veicolo_libero(base_id: int, giorno: str, impegnati: set[int]) -> int | None:
    """Mezzo della base non gia' impegnato in giornata."""
    candidati = db.query(
        "SELECT id FROM veicoli WHERE sito_base = ? AND disponibile = 1 ORDER BY id", (base_id,)
    )
    occupati = {
        r["veicolo_id"]
        for r in db.query(
            "SELECT veicolo_id FROM viaggi WHERE data = ? AND veicolo_id IS NOT NULL", (giorno,)
        )
    } | impegnati
    for veicolo in candidati:
        if veicolo["id"] not in occupati:
            return veicolo["id"]
    return None


def _esito_tappa(tappa: dict, rnd: random.Random) -> dict:
    """Estrae l'esito di una tappa: orario, quantita' e causale."""
    ora = tappa["ora_prevista"]
    data = tappa["data_prevista"]
    causale = None

    estrazione = rnd.random()
    if estrazione < PROB_RINVIO_GIORNO:
        data = (date.fromisoformat(data) + timedelta(days=1)).isoformat()
        ora = max(tappa["ora_prevista"] - rnd.uniform(0, 2), 8.0)
        causale = rnd.choice(CAUSALI_RINVIO)
    elif estrazione < PROB_RINVIO_GIORNO + PROB_RITARDO_GRAVE:
        ora += rnd.uniform(1.1, 3.4)
        causale = rnd.choice(CAUSALI_RITARDO)
    elif estrazione < PROB_RINVIO_GIORNO + PROB_RITARDO_GRAVE + PROB_RITARDO_LIEVE:
        ora += rnd.uniform(0.2, 1.0)
        causale = rnd.choice(CAUSALI_RITARDO)
    else:
        # Consegna nella norma: piccolo scarto attorno all'orario previsto.
        ora += rnd.uniform(-0.35, 0.45)
    ora = min(max(ora, 0.0), 23.98)

    quantita: dict[int, float] = {}
    non_eseguita = False
    estrazione = rnd.random()
    if estrazione < PROB_NON_ESEGUITA:
        non_eseguita = True
        causale = rnd.choice(CAUSALI_RIFIUTO)
    elif estrazione < PROB_NON_ESEGUITA + PROB_PARZIALE and tappa["righe"]:
        riga = rnd.choice(tappa["righe"])
        quantita[riga["id"]] = round(riga["quantita_richiesta"] * rnd.uniform(0.35, 0.9), 1)
        causale = causale or rnd.choice(CAUSALI_PARZIALE)

    return {
        "data_effettiva": data,
        "ora_effettiva": round(ora, 2),
        "quantita": quantita,
        "causale": causale,
        "non_eseguita": non_eseguita,
    }


def simula_esecuzione(fino_a: str | None = None, seed: int = 11) -> dict:
    """Esegue i viaggi pianificati fino alla data indicata e li chiude.

    Restituisce il riepilogo di quanto simulato: viaggi eseguiti, tappe
    registrate e scostamento complessivo di costo.
    """
    rnd = random.Random(seed)
    viaggi = esecuzione.elenco_viaggi(stato="PIANIFICATO", data_a=fino_a, limite=1000)
    impegnati: set[int] = set()
    eseguiti = tappe_registrate = 0
    costo_previsto = costo_effettivo = 0.0

    for sintesi in viaggi:
        viaggio = esecuzione.dettaglio_viaggio(sintesi["id"])
        # I mezzi aziendali sono un costo gia' sostenuto: si saturano prima
        # di comprare trasporto sul mercato, indipendentemente dal
        # suggerimento economico del piano.
        veicolo = _veicolo_libero(viaggio["origine_id"], viaggio["data"], impegnati)
        if veicolo:
            impegnati.add(veicolo)
            esecuzione.assegna(viaggio["id"], veicolo_id=veicolo, autista=_autista(rnd))
        else:
            vettori = db.query("SELECT id FROM vettori ORDER BY id")
            esecuzione.assegna(viaggio["id"], vettore_id=rnd.choice(vettori)["id"])

        partenza = f"{viaggio['data']}T{_orario(viaggio['partenza_prevista'] + rnd.uniform(-0.2, 0.6))}"
        esecuzione.registra_partenza(viaggio["id"], partenza)

        for tappa in viaggio["tappe"]:
            esito = _esito_tappa(tappa, rnd)
            esecuzione.registra_esito_tappa(tappa["id"], **esito)
            tappe_registrate += 1

        # A consuntivo i km crescono quasi sempre (deviazioni, ricerca
        # dell'indirizzo, ritorni a vuoto); il costo segue i km piu' le soste.
        km = viaggio["km_previsti"] * rnd.uniform(1.0, 1.09)
        costo = viaggio["costo_previsto"] * rnd.uniform(0.97, 1.14)
        esecuzione.chiudi_viaggio(viaggio["id"], round(km, 1), round(costo, 2))
        eseguiti += 1
        costo_previsto += viaggio["costo_previsto"]
        costo_effettivo += costo

    return {
        "viaggi_eseguiti": eseguiti,
        "tappe_registrate": tappe_registrate,
        "costo_previsto": round(costo_previsto, 2),
        "costo_effettivo": round(costo_effettivo, 2),
        "scostamento_pct": round(
            (costo_effettivo - costo_previsto) / costo_previsto * 100, 1
        )
        if costo_previsto
        else 0.0,
    }


NOMI = ["M. Rossi", "A. Bianchi", "G. Esposito", "L. Ferrari", "S. Romano", "D. Greco",
        "P. Marino", "F. Conti", "R. Gallo", "C. Costa", "V. Rizzo", "N. Lombardi"]


def _autista(rnd: random.Random) -> str:
    return rnd.choice(NOMI)


def _orario(ora: float) -> str:
    ora = min(max(ora, 0.0), 23.98)
    ore = int(ora)
    minuti = int(round((ora - ore) * 60))
    if minuti == 60:
        ore, minuti = ore + 1, 0
    return f"{ore:02d}:{minuti:02d}:00"


if __name__ == "__main__":
    print(simula_esecuzione())
