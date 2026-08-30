"""Misura del livello di servizio a consuntivo (OTIF) e scostamenti di costo.

L'OTIF si calcola **per ordine**, non per viaggio: e' il cliente a
percepire il servizio, e un ordine consegnato a meta' resta un ordine
mancato anche se il giro e' filato liscio.

* **On Time** - consegna entro la finestra concordata: la data richiesta
  dall'ordine e l'orario di chiusura del sito destinatario, con una
  franchigia in minuti. La consegna anticipata e' ammessa per default, ma
  puo' essere conteggiata come non puntuale (molti clienti con magazzini
  a flusso teso non la accettano).
* **In Full** - ogni riga dell'ordine consegnata per intero, entro
  l'eventuale tolleranza percentuale.
* **OTIF** - entrambe le condizioni. Gli indicatori parziali restano
  visibili: separano i problemi di trasporto da quelli di disponibilita'.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .. import db
from .esecuzione import (
    CAUSALE_PIANO,
    CAUSALI,
    DESCRIZIONE_CAUSALE_PIANO,
    TOLLERANZA_QUANTITA_PCT,
    TOLLERANZA_RITARDO_MINUTI,
)


def _percentuale(parte: float, totale: float) -> float:
    return round(parte / totale * 100, 1) if totale else 0.0


def dettaglio_ordini(
    data_da: str | None = None,
    data_a: str | None = None,
    tolleranza_minuti: float = TOLLERANZA_RITARDO_MINUTI,
    tolleranza_quantita_pct: float = TOLLERANZA_QUANTITA_PCT,
    accetta_anticipo: bool = True,
) -> list[dict]:
    """Esito di servizio per ogni ordine con almeno una consegna registrata."""
    condizioni = ["r.quantita_consegnata IS NOT NULL"]
    parametri: list = []
    if data_da:
        condizioni.append("o.data_richiesta >= ?")
        parametri.append(data_da)
    if data_a:
        condizioni.append("o.data_richiesta <= ?")
        parametri.append(data_a)

    righe = db.query(
        f"""SELECT r.ordine_id, r.articolo_id, r.quantita_richiesta, r.quantita_consegnata,
                   o.riferimento, o.data_richiesta, o.priorita,
                   t.id AS tappa_id, t.data_effettiva, t.ora_effettiva, t.stato AS stato_tappa,
                   t.causale, t.data_prevista, t.ora_prevista,
                   d.id AS destino_id, d.nome AS destino_nome, d.comune, d.provincia,
                   d.apertura, d.chiusura,
                   v.id AS viaggio_id, v.giro_id, v.esecuzione, v.profilo,
                   ve.targa AS veicolo_targa, ve2.nome AS vettore_nome
            FROM tappe_righe r
            JOIN viaggi_tappe t ON t.id = r.tappa_id
            JOIN viaggi v ON v.id = t.viaggio_id
            JOIN ordini o ON o.id = r.ordine_id
            JOIN siti d ON d.id = o.destino_id
            LEFT JOIN veicoli ve ON ve.id = v.veicolo_id
            LEFT JOIN vettori ve2 ON ve2.id = v.vettore_id
            WHERE {' AND '.join(condizioni)}
            ORDER BY o.data_richiesta, o.riferimento""",
        tuple(parametri),
    )

    per_ordine: dict[int, list[dict]] = defaultdict(list)
    for riga in righe:
        per_ordine[riga["ordine_id"]].append(riga)

    esiti = []
    for ordine_id, gruppo in per_ordine.items():
        capo = gruppo[-1]  # ultima consegna registrata per l'ordine
        richiesta = sum(r["quantita_richiesta"] for r in gruppo)
        consegnata = sum(r["quantita_consegnata"] for r in gruppo)

        in_full = all(
            r["quantita_consegnata"] >= r["quantita_richiesta"] * (1 - tolleranza_quantita_pct) - 1e-9
            for r in gruppo
        )
        eseguita = capo["stato_tappa"] != "NON_ESEGUITA" and consegnata > 0

        limite = capo["chiusura"] + tolleranza_minuti / 60

        def valuta(data_consegna: str, ora_consegna: float) -> tuple[bool, float]:
            """Puntualita' e ritardo rispetto alla finestra concordata."""
            giorni = (
                date.fromisoformat(data_consegna) - date.fromisoformat(capo["data_richiesta"])
            ).days
            if giorni < 0:
                return accetta_anticipo, 0.0 if accetta_anticipo else round(-giorni * 24 * 60, 1)
            puntuale = giorni == 0 and ora_consegna <= limite + 1e-9
            return puntuale, max(round((giorni * 24 + ora_consegna - limite) * 60, 1), 0.0)

        on_time, ritardo = valuta(capo["data_effettiva"], capo["ora_effettiva"])
        on_time = on_time and eseguita
        # Se anche l'orario previsto dal piano cadeva fuori finestra, il
        # ritardo non nasce dall'esecuzione ma dalla pianificazione.
        puntuale_da_piano, ritardo_da_piano = valuta(capo["data_prevista"], capo["ora_prevista"])
        causale = capo["causale"] or (None if puntuale_da_piano or on_time else CAUSALE_PIANO)

        esiti.append(
            {
                "ordine_id": ordine_id,
                "riferimento": capo["riferimento"],
                "data_richiesta": capo["data_richiesta"],
                "data_consegna": capo["data_effettiva"],
                "ora_consegna": capo["ora_effettiva"],
                "priorita": capo["priorita"],
                "destino_id": capo["destino_id"],
                "destino_nome": capo["destino_nome"],
                "comune": capo["comune"],
                "provincia": capo["provincia"],
                "viaggio_id": capo["viaggio_id"],
                "giro_id": capo["giro_id"],
                "esecuzione": capo["esecuzione"],
                "operatore": capo["vettore_nome"] or capo["veicolo_targa"] or "-",
                "stato_tappa": capo["stato_tappa"],
                "causale": causale,
                "causale_descrizione": CAUSALI.get(causale or "", None)
                or (DESCRIZIONE_CAUSALE_PIANO if causale == CAUSALE_PIANO else None),
                "ritardo_da_piano_minuti": ritardo_da_piano,
                "quantita_richiesta": round(richiesta, 1),
                "quantita_consegnata": round(consegnata, 1),
                "quantita_mancante": round(max(richiesta - consegnata, 0), 1),
                "completezza_pct": _percentuale(consegnata, richiesta),
                "ritardo_minuti": ritardo,
                "on_time": on_time,
                "in_full": in_full and eseguita,
                "otif": on_time and in_full and eseguita,
            }
        )
    esiti.sort(key=lambda e: (e["data_richiesta"], e["riferimento"]))
    return esiti


def _aggrega(esiti: list[dict], chiave) -> list[dict]:
    gruppi: dict = defaultdict(list)
    for e in esiti:
        gruppi[chiave(e)].append(e)
    risultato = [
        {
            "voce": voce,
            "ordini": len(gruppo),
            "on_time_pct": _percentuale(sum(1 for e in gruppo if e["on_time"]), len(gruppo)),
            "in_full_pct": _percentuale(sum(1 for e in gruppo if e["in_full"]), len(gruppo)),
            "otif_pct": _percentuale(sum(1 for e in gruppo if e["otif"]), len(gruppo)),
            "ritardo_medio_minuti": round(
                sum(e["ritardo_minuti"] for e in gruppo) / len(gruppo), 1
            ),
        }
        for voce, gruppo in gruppi.items()
    ]
    risultato.sort(key=lambda r: (r["otif_pct"], -r["ordini"]))
    return risultato


def cruscotto_otif(
    data_da: str | None = None,
    data_a: str | None = None,
    tolleranza_minuti: float = TOLLERANZA_RITARDO_MINUTI,
    tolleranza_quantita_pct: float = TOLLERANZA_QUANTITA_PCT,
    accetta_anticipo: bool = True,
) -> dict:
    """OTIF complessivo con le sue scomposizioni e le cause del mancato servizio."""
    esiti = dettaglio_ordini(
        data_da, data_a, tolleranza_minuti, tolleranza_quantita_pct, accetta_anticipo
    )
    totale = len(esiti)
    if not totale:
        return {
            "parametri": {
                "tolleranza_minuti": tolleranza_minuti,
                "tolleranza_quantita_pct": tolleranza_quantita_pct,
                "accetta_anticipo": accetta_anticipo,
            },
            "totali": {"ordini": 0, "on_time_pct": 0.0, "in_full_pct": 0.0, "otif_pct": 0.0},
            "mancati": [],
            "per_cliente": [],
            "per_esecuzione": [],
            "per_causale": [],
            "per_giorno": [],
            "peggiori": [],
        }

    on_time = sum(1 for e in esiti if e["on_time"])
    in_full = sum(1 for e in esiti if e["in_full"])
    otif = sum(1 for e in esiti if e["otif"])
    solo_ritardo = sum(1 for e in esiti if not e["on_time"] and e["in_full"])
    solo_incompleto = sum(1 for e in esiti if e["on_time"] and not e["in_full"])
    entrambi = sum(1 for e in esiti if not e["on_time"] and not e["in_full"])
    ritardati = [e for e in esiti if e["ritardo_minuti"] > 0]

    per_causale = _aggrega(
        [e for e in esiti if not e["otif"]],
        lambda e: CAUSALI.get(e["causale"] or "", None)
        or (DESCRIZIONE_CAUSALE_PIANO if e["causale"] == CAUSALE_PIANO else "Causale non registrata"),
    )
    for voce in per_causale:
        voce["quota_pct"] = _percentuale(voce["ordini"], totale - otif)

    return {
        "parametri": {
            "tolleranza_minuti": tolleranza_minuti,
            "tolleranza_quantita_pct": tolleranza_quantita_pct,
            "accetta_anticipo": accetta_anticipo,
        },
        "totali": {
            "ordini": totale,
            "on_time": on_time,
            "in_full": in_full,
            "otif": otif,
            "on_time_pct": _percentuale(on_time, totale),
            "in_full_pct": _percentuale(in_full, totale),
            "otif_pct": _percentuale(otif, totale),
            "ritardi": len(ritardati),
            "ritardo_medio_ritardati_minuti": round(
                sum(e["ritardo_minuti"] for e in ritardati) / len(ritardati), 1
            )
            if ritardati
            else 0.0,
            "ritardo_da_piano": sum(1 for e in esiti if e["causale"] == CAUSALE_PIANO),
            "quantita_mancante": round(sum(e["quantita_mancante"] for e in esiti), 1),
            "completezza_media_pct": round(
                sum(e["completezza_pct"] for e in esiti) / totale, 1
            ),
        },
        "mancati": [
            {"motivo": "Solo in ritardo", "ordini": solo_ritardo, "quota_pct": _percentuale(solo_ritardo, totale)},
            {"motivo": "Solo incompleto", "ordini": solo_incompleto, "quota_pct": _percentuale(solo_incompleto, totale)},
            {"motivo": "In ritardo e incompleto", "ordini": entrambi, "quota_pct": _percentuale(entrambi, totale)},
        ],
        "per_cliente": _aggrega(esiti, lambda e: e["destino_nome"]),
        "per_esecuzione": _aggrega(
            esiti, lambda e: "Flotta propria" if e["esecuzione"] == "PROPRIO" else "Vettore terzo"
        ),
        "per_causale": per_causale,
        "per_giorno": sorted(_aggrega(esiti, lambda e: e["data_richiesta"]), key=lambda r: r["voce"]),
        "peggiori": sorted(
            [e for e in esiti if not e["otif"]],
            key=lambda e: (-e["ritardo_minuti"], -e["quantita_mancante"]),
        )[:15],
    }


def consuntivo_costi(data_da: str | None = None, data_a: str | None = None) -> dict:
    """Confronto fra costo pianificato e costo effettivo dei viaggi chiusi."""
    condizioni = ["stato = 'COMPLETATO'"]
    parametri: list = []
    if data_da:
        condizioni.append("data >= ?")
        parametri.append(data_da)
    if data_a:
        condizioni.append("data <= ?")
        parametri.append(data_a)

    viaggi = db.query(
        f"""SELECT id, giro_id, data, esecuzione, km_previsti, km_effettivi,
                   costo_previsto, costo_effettivo
            FROM viaggi WHERE {' AND '.join(condizioni)} ORDER BY data, giro_id""",
        tuple(parametri),
    )
    if not viaggi:
        return {"viaggi": 0, "totali": {}, "per_esecuzione": [], "scostamenti_maggiori": []}

    previsto = sum(v["costo_previsto"] for v in viaggi)
    effettivo = sum(v["costo_effettivo"] or 0 for v in viaggi)
    km_previsti = sum(v["km_previsti"] for v in viaggi)
    km_effettivi = sum(v["km_effettivi"] or 0 for v in viaggi)

    for v in viaggi:
        v["scostamento_eur"] = round((v["costo_effettivo"] or 0) - v["costo_previsto"], 2)
        v["scostamento_pct"] = _percentuale(v["scostamento_eur"], v["costo_previsto"])
        v["scostamento_km"] = round((v["km_effettivi"] or 0) - v["km_previsti"], 1)

    gruppi: dict[str, list[dict]] = defaultdict(list)
    for v in viaggi:
        gruppi[v["esecuzione"]].append(v)

    return {
        "viaggi": len(viaggi),
        "totali": {
            "costo_previsto": round(previsto, 2),
            "costo_effettivo": round(effettivo, 2),
            "scostamento_eur": round(effettivo - previsto, 2),
            "scostamento_pct": _percentuale(effettivo - previsto, previsto),
            "km_previsti": round(km_previsti, 1),
            "km_effettivi": round(km_effettivi, 1),
            "scostamento_km_pct": _percentuale(km_effettivi - km_previsti, km_previsti),
            "costo_km_previsto": round(previsto / km_previsti, 3) if km_previsti else 0.0,
            "costo_km_effettivo": round(effettivo / km_effettivi, 3) if km_effettivi else 0.0,
        },
        "per_esecuzione": [
            {
                "voce": "Flotta propria" if chiave == "PROPRIO" else "Vettore terzo",
                "viaggi": len(gruppo),
                "costo_previsto": round(sum(v["costo_previsto"] for v in gruppo), 2),
                "costo_effettivo": round(sum(v["costo_effettivo"] or 0 for v in gruppo), 2),
                "scostamento_pct": _percentuale(
                    sum(v["scostamento_eur"] for v in gruppo),
                    sum(v["costo_previsto"] for v in gruppo),
                ),
            }
            for chiave, gruppo in sorted(gruppi.items())
        ],
        "scostamenti_maggiori": sorted(viaggi, key=lambda v: -abs(v["scostamento_eur"]))[:12],
    }
