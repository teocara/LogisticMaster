"""Orchestrazione del piano logistico giornaliero.

Collega i moduli di calcolo ai dati anagrafici: parte dagli ordini da
pianificare e dalle giacenze, produce i trasferimenti inter-sito, i
carichi consolidati, i giri ottimizzati e il confronto economico rispetto
allo scenario "una spedizione dedicata per ordine".
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

from .. import db
from .consolidamento import Carico, RigaCarico, Spedizione, consolida, pallet_necessari
from .costi import (
    PROFILI_VEICOLO,
    TariffaVettore,
    co2_kg,
    costo_flotta_propria,
    costo_vettore,
    durata_sosta_ore,
)
from .geo import MatriceDistanze, Punto
from .riordino import Squilibrio, calcola_parametri, piano_bilanciamento
from .vrp import Fermata, ottimizza_giri


def _punti(siti: list[dict]) -> MatriceDistanze:
    return MatriceDistanze([Punto(s["id"], s["lat"], s["lon"]) for s in siti])


def carica_siti() -> dict[int, dict]:
    return {s["id"]: s for s in db.query("SELECT * FROM siti WHERE attivo = 1")}


def carica_articoli() -> dict[int, dict]:
    return {a["id"]: a for a in db.query("SELECT * FROM articoli")}


# --------------------------------------------------------------------------
# 1. Analisi scorte e trasferimenti inter-sito
# --------------------------------------------------------------------------


def analisi_scorte() -> dict:
    """Parametri di scorta e criticita' per ogni coppia sito/articolo."""
    righe = db.query(
        """SELECT g.*, s.codice AS sito_codice, s.nome AS sito_nome, s.tipo AS sito_tipo,
                  a.codice AS articolo_codice, a.descrizione AS articolo_descrizione,
                  a.valore_unitario, a.classe_abc
           FROM giacenze g
           JOIN siti s ON s.id = g.sito_id
           JOIN articoli a ON a.id = g.articolo_id"""
    )
    risultati = []
    for r in righe:
        parametri = calcola_parametri(
            sito_id=r["sito_id"],
            articolo_id=r["articolo_id"],
            domanda_media_giorno=r["domanda_media_giorno"],
            deviazione_domanda_giorno=r["deviazione_domanda"],
            lead_time_giorni=r["lead_time_giorni"],
            deviazione_lead_time_giorni=r["deviazione_lead_time"],
            livello_servizio=r["livello_servizio"],
            giacenza=r["quantita"] - r["impegnata"],
            valore_unitario=r["valore_unitario"],
        )
        voce = parametri.as_dict()
        disponibile = r["quantita"] - r["impegnata"]
        voce.update(
            {
                "sito_codice": r["sito_codice"],
                "sito_nome": r["sito_nome"],
                "sito_tipo": r["sito_tipo"],
                "articolo_codice": r["articolo_codice"],
                "articolo_descrizione": r["articolo_descrizione"],
                "classe_abc": r["classe_abc"],
                "giacenza": r["quantita"],
                "impegnata": r["impegnata"],
                "disponibile": disponibile,
                "valore_giacenza": round(r["quantita"] * r["valore_unitario"], 2),
                "sotto_riordino": disponibile < parametri.punto_riordino,
                "eccedenza": max(disponibile - parametri.punto_riordino, 0),
            }
        )
        risultati.append(voce)
    risultati.sort(key=lambda v: v["copertura_giorni"])
    return {
        "righe": risultati,
        "sotto_riordino": sum(1 for v in risultati if v["sotto_riordino"]),
        "valore_giacenze": round(sum(v["valore_giacenza"] for v in risultati), 2),
    }


def proposte_trasferimenti(km_massimi: float = 900.0) -> dict:
    """Trasferimenti inter-sito che coprono i fabbisogni con le eccedenze."""
    analisi = analisi_scorte()
    siti = carica_siti()
    articoli = carica_articoli()
    matrice = _punti(list(siti.values()))

    squilibri = [
        Squilibrio(
            sito_id=v["sito_id"],
            articolo_id=v["articolo_id"],
            giacenza=v["disponibile"],
            punto_riordino=v["punto_riordino"],
            scorta_massima=v["disponibile"] + v["punto_riordino"] * 3,
        )
        for v in analisi["righe"]
    ]
    coperture = {(v["sito_id"], v["articolo_id"]): v["copertura_giorni"] for v in analisi["righe"]}

    proposte = piano_bilanciamento(squilibri, matrice, coperture, km_massimi=km_massimi)

    arricchite = []
    valore_movimentato = 0.0
    for p in proposte:
        voce = p.as_dict()
        articolo = articoli.get(p.articolo_id, {})
        origine = siti.get(p.origine_id)
        voce.update(
            {
                "articolo_codice": articolo.get("codice", "-"),
                "articolo_descrizione": articolo.get("descrizione", "-"),
                "origine_codice": origine["codice"] if origine else "PRODUZIONE",
                "origine_nome": origine["nome"] if origine else "Riordino a produzione/fornitore",
                "destino_codice": siti[p.destino_id]["codice"],
                "destino_nome": siti[p.destino_id]["nome"],
                "peso_kg": round(p.quantita * articolo.get("peso_kg", 0), 1),
                "pallet": round(
                    pallet_necessari(
                        p.quantita,
                        articolo.get("pezzi_per_pallet", 100),
                        bool(articolo.get("sovrapponibile", 1)),
                    ),
                    2,
                ),
                "valore": round(p.quantita * articolo.get("valore_unitario", 0), 2),
            }
        )
        valore_movimentato += voce["valore"]
        arricchite.append(voce)

    return {
        "proposte": arricchite,
        "totale": len(arricchite),
        "da_rete": sum(1 for v in arricchite if v["origine_id"] != 0),
        "da_produzione": sum(1 for v in arricchite if v["origine_id"] == 0),
        "valore_movimentato": round(valore_movimentato, 2),
    }


# --------------------------------------------------------------------------
# 2. Dagli ordini alle spedizioni
# --------------------------------------------------------------------------


def spedizioni_da_ordini(
    data_da: str | None = None, data_a: str | None = None, stato: str = "DA_PIANIFICARE"
) -> list[Spedizione]:
    """Converte gli ordini in spedizioni con peso, volume e pallet."""
    condizioni = ["o.stato = ?"]
    parametri: list = [stato]
    if data_da:
        condizioni.append("o.data_richiesta >= ?")
        parametri.append(data_da)
    if data_a:
        condizioni.append("o.data_richiesta <= ?")
        parametri.append(data_a)

    ordini = db.query(
        f"""SELECT o.*, d.apertura AS apertura, d.chiusura AS chiusura
            FROM ordini o JOIN siti d ON d.id = o.destino_id
            WHERE {' AND '.join(condizioni)}
            ORDER BY o.data_richiesta, o.priorita""",
        tuple(parametri),
    )
    if not ordini:
        return []

    articoli = carica_articoli()
    righe_per_ordine: dict[int, list[dict]] = {}
    for r in db.query(
        "SELECT * FROM ordini_righe WHERE ordine_id IN (%s)"
        % ",".join(str(o["id"]) for o in ordini)
    ):
        righe_per_ordine.setdefault(r["ordine_id"], []).append(r)

    spedizioni: list[Spedizione] = []
    for o in ordini:
        righe = []
        for r in righe_per_ordine.get(o["id"], []):
            a = articoli[r["articolo_id"]]
            righe.append(
                RigaCarico(
                    ordine_id=o["id"],
                    articolo_id=a["id"],
                    quantita=r["quantita"],
                    peso_kg=r["quantita"] * a["peso_kg"],
                    volume_m3=r["quantita"] * a["volume_m3"],
                    pallet=pallet_necessari(
                        r["quantita"], a["pezzi_per_pallet"], bool(a["sovrapponibile"])
                    ),
                    adr=bool(a["adr"]),
                    sovrapponibile=bool(a["sovrapponibile"]),
                    temperatura_controllata=bool(a["temperatura_controllata"]),
                )
            )
        if not righe:
            continue
        spedizioni.append(
            Spedizione(
                id=o["riferimento"],
                origine_id=o["origine_id"],
                destino_id=o["destino_id"],
                data_richiesta=o["data_richiesta"],
                priorita=o["priorita"],
                righe=righe,
                finestra_apertura=o["apertura"],
                finestra_chiusura=o["chiusura"],
            )
        )
    return spedizioni


# --------------------------------------------------------------------------
# 3. Piano di trasporto completo
# --------------------------------------------------------------------------


@dataclass
class ParametriPiano:
    data_da: str | None = None
    data_a: str | None = None
    ora_partenza: float = 6.0
    soglia_groupage_pct: float = 55.0
    profilo_predefinito: str = "MOTRICE_180"
    sconto_vettore_pct: float = 0.12


def _fermate_da_spedizioni(spedizioni: list[Spedizione], siti: dict[int, dict]) -> list[Fermata]:
    """Aggrega le spedizioni per destinazione in una sola fermata."""
    per_destino: dict[int, list[Spedizione]] = {}
    for s in spedizioni:
        per_destino.setdefault(s.destino_id, []).append(s)
    fermate = []
    for destino_id, gruppo in per_destino.items():
        sito = siti[destino_id]
        fermate.append(
            Fermata(
                id=f"F{destino_id}",
                sito_id=destino_id,
                peso_kg=sum(s.peso_kg for s in gruppo),
                volume_m3=sum(s.volume_m3 for s in gruppo),
                pallet=sum(s.pallet for s in gruppo),
                apertura=sito["apertura"],
                chiusura=sito["chiusura"],
                priorita=min(s.priorita for s in gruppo),
                spedizioni=[s.id for s in gruppo],
            )
        )
    return fermate


def _scenario_base(
    spedizioni: list[Spedizione], matrice: MatriceDistanze, profilo_codice: str
) -> dict:
    """Scenario "as-is": una missione dedicata per ogni ordine (andata/ritorno)."""
    profilo = PROFILI_VEICOLO[profilo_codice]
    km = costo = co2 = 0.0
    for s in spedizioni:
        tratta = matrice.km(s.origine_id, s.destino_id) * 2
        ore = matrice.ore_guida(s.origine_id, s.destino_id) * 2
        traghetto = matrice.traghetto(s.origine_id, s.destino_id)
        dettaglio = costo_flotta_propria(
            profilo,
            tratta,
            ore,
            durata_sosta_ore(s.pallet),
            giorni_impegno=max(1.0, math.ceil(ore / 9.0)),
            costo_traghetti=(traghetto["costo_eur"] * 2) if traghetto else 0.0,
        )
        km += tratta
        costo += dettaglio.totale
        co2 += co2_kg(profilo, tratta)
    return {
        "descrizione": "Una missione dedicata per ordine, senza consolidamento",
        "missioni": len(spedizioni),
        "km": round(km, 1),
        "costo_eur": round(costo, 2),
        "co2_kg": round(co2, 1),
    }


def genera_piano(parametri: ParametriPiano | None = None) -> dict:
    """Genera il piano di trasporto completo con KPI e confronto scenari."""
    parametri = parametri or ParametriPiano()
    siti = carica_siti()
    matrice = _punti(list(siti.values()))
    spedizioni = spedizioni_da_ordini(parametri.data_da, parametri.data_a)

    if not spedizioni:
        return {
            "generato_il": datetime.now().isoformat(timespec="seconds"),
            "parametri": parametri.__dict__,
            "spedizioni": 0,
            "giri": [],
            "carichi": [],
            "groupage": [],
            "kpi": {},
            "scenario_base": {},
            "confronto": {},
        }

    profilo = PROFILI_VEICOLO[parametri.profilo_predefinito]
    tariffa = TariffaVettore(nome="Vettore convenzionato", sconto_pct=parametri.sconto_vettore_pct)

    # Consolidamento per origine/data.
    carichi: list[Carico] = consolida(spedizioni)

    # Giri ottimizzati per ciascuna coppia origine/data.
    gruppi: dict[tuple[int, str], list[Spedizione]] = {}
    for s in spedizioni:
        gruppi.setdefault((s.origine_id, s.data_richiesta), []).append(s)

    giri = []
    groupage = []
    indice = 1
    for (origine_id, data), gruppo in sorted(gruppi.items(), key=lambda x: (x[0][1], x[0][0])):
        fermate = _fermate_da_spedizioni(gruppo, siti)
        risultato = ottimizza_giri(
            origine_id,
            fermate,
            matrice,
            profilo=profilo,
            ora_partenza=parametri.ora_partenza,
            prefisso="GIRO",
        )
        for giro in risultato:
            voce = giro.as_dict()
            voce["data"] = data
            voce["origine_codice"] = siti[origine_id]["codice"]
            voce["origine_nome"] = siti[origine_id]["nome"]
            voce["fermate_nomi"] = [siti[f.sito_id]["nome"] for f in giro.fermate]
            # Identificativo leggibile: giorno del piano + progressivo globale.
            voce["id"] = f"G{data[5:7]}{data[8:10]}-{indice:03d}"
            indice += 1

            # Confronto make-or-buy sul singolo giro. Le destinazioni
            # isolane scontano la maggiorazione di listino del vettore.
            verso_isole = any(
                matrice.traghetto(x, y)
                for x, y in zip(
                    [origine_id, *voce["sequenza"]], [*voce["sequenza"], origine_id]
                )
            )
            terzi = costo_vettore(
                giro.peso_kg, giro.volume_m3, giro.km, tariffa, isole=verso_isole
            )
            voce["verso_isole"] = verso_isole
            voce["costo_conto_terzi"] = terzi.totale
            voce["scelta_consigliata"] = (
                "PROPRIO" if giro.costo.totale <= terzi.totale else "TERZI"
            )
            voce["delta_make_or_buy"] = round(giro.costo.totale - terzi.totale, 2)

            if giro.saturazione_pct() < parametri.soglia_groupage_pct:
                groupage.append(
                    {
                        "giro_id": voce["id"],
                        "saturazione_pct": giro.saturazione_pct(),
                        "km": voce["km"],
                        "costo_proprio": giro.costo.totale,
                        "costo_terzi": terzi.totale,
                        "risparmio_potenziale": round(giro.costo.totale - terzi.totale, 2),
                    }
                )
            giri.append(voce)

    km_totali = sum(g["km"] for g in giri)
    costo_totale = sum(g["costo"]["totale"] for g in giri)
    costo_ottimizzato = sum(
        min(g["costo"]["totale"], g["costo_conto_terzi"]) for g in giri
    )
    peso_totale = sum(g["peso_kg"] for g in giri)
    pallet_totali = sum(g["pallet"] for g in giri)
    co2_totale = sum(g["co2_kg"] for g in giri)
    # Le tonnellate-chilometro si calcolano giro per giro: il carico medio
    # trasportato non e' il totale della rete moltiplicato per i km totali.
    ton_km = sum(g["peso_kg"] / 1000 * g["km"] for g in giri)
    base = _scenario_base(spedizioni, matrice, parametri.profilo_predefinito)

    kpi = {
        "spedizioni": len(spedizioni),
        "giri_non_ammissibili": sum(1 for g in giri if not g["ammissibile"]),
        "giri_multigiorno": sum(1 for g in giri if g["giorni_impegno"] > 1),
        "costo_traghetti_eur": round(sum(g["costo"]["traghetti"] for g in giri), 2),
        "giri": len(giri),
        "fermate": sum(len(g["sequenza"]) for g in giri),
        "km_totali": round(km_totali, 1),
        "km_per_fermata": round(km_totali / max(sum(len(g["sequenza"]) for g in giri), 1), 1),
        "costo_totale_eur": round(costo_totale, 2),
        "costo_ottimizzato_eur": round(costo_ottimizzato, 2),
        "costo_per_km": round(costo_totale / km_totali, 3) if km_totali else 0.0,
        "costo_per_pallet": round(costo_totale / pallet_totali, 2) if pallet_totali else 0.0,
        "costo_per_ton_km": round(costo_totale / ton_km, 3) if ton_km else 0.0,
        "ton_km": round(ton_km, 1),
        "peso_totale_kg": round(peso_totale, 1),
        "pallet_totali": round(pallet_totali, 1),
        "saturazione_media_pct": round(
            sum(g["saturazione_pct"] for g in giri) / len(giri), 1
        )
        if giri
        else 0.0,
        "co2_kg": round(co2_totale, 1),
        "co2_g_per_ton_km": round(co2_totale * 1000 / ton_km, 1) if ton_km else 0.0,
        "giri_sottosaturi": len(groupage),
        "carichi": len(carichi),
    }

    confronto = {
        "km_risparmiati": round(base["km"] - km_totali, 1),
        "km_risparmiati_pct": round((base["km"] - km_totali) / base["km"] * 100, 1)
        if base["km"]
        else 0.0,
        "costo_risparmiato_eur": round(base["costo_eur"] - costo_ottimizzato, 2),
        "costo_risparmiato_pct": round(
            (base["costo_eur"] - costo_ottimizzato) / base["costo_eur"] * 100, 1
        )
        if base["costo_eur"]
        else 0.0,
        "co2_risparmiata_kg": round(base["co2_kg"] - co2_totale, 1),
        "missioni_evitate": base["missioni"] - len(giri),
        # Scomposizione del risparmio nelle due leve applicate.
        "risparmio_da_consolidamento_eur": round(base["costo_eur"] - costo_totale, 2),
        "risparmio_da_make_or_buy_eur": round(costo_totale - costo_ottimizzato, 2),
    }

    return {
        "generato_il": datetime.now().isoformat(timespec="seconds"),
        "parametri": parametri.__dict__,
        "spedizioni": len(spedizioni),
        "giri": giri,
        "carichi": [c.as_dict() for c in carichi],
        "groupage": groupage,
        "kpi": kpi,
        "scenario_base": base,
        "confronto": confronto,
    }


def salva_piano(risultato: dict, descrizione: str = "") -> int:
    """Persiste il piano e ne genera i viaggi eseguibili."""
    piano_id = db.esegui(
        "INSERT INTO piani (creato_il,data_riferimento,descrizione,parametri,risultato) VALUES (?,?,?,?,?)",
        (
            datetime.now().isoformat(timespec="seconds"),
            risultato["parametri"].get("data_da") or datetime.now().date().isoformat(),
            descrizione or "Piano di trasporto",
            json.dumps(risultato["parametri"], ensure_ascii=False),
            json.dumps(risultato, ensure_ascii=False),
        ),
    )
    from .esecuzione import crea_viaggi_da_piano

    risultato["viaggi"] = crea_viaggi_da_piano(piano_id, risultato)
    return piano_id
