"""API di esecuzione: viaggi in corso, esiti delle tappe, OTIF a consuntivo."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..core import esecuzione, otif
from ..models import (
    AnnullamentoInput,
    AssegnazioneInput,
    ChiusuraViaggioInput,
    EsitoTappaInput,
    PartenzaInput,
)

router = APIRouter(prefix="/api", tags=["esecuzione"])


def _esegui(operazione):
    """Traduce gli errori di dominio in risposte HTTP comprensibili."""
    try:
        return operazione()
    except esecuzione.ErroreEsecuzione as errore:
        messaggio = str(errore)
        raise HTTPException(404 if "inesistente" in messaggio else 409, messaggio) from errore


@router.get("/viaggi")
def elenco_viaggi(
    stato: str | None = None,
    data_da: str | None = None,
    data_a: str | None = None,
    piano_id: int | None = None,
    limite: int = Query(default=200, le=1000),
) -> list[dict]:
    """Viaggi con stato, avanzamento delle tappe e scostamento a consuntivo."""
    if stato and stato not in esecuzione.TRANSIZIONI:
        raise HTTPException(422, f"Stato non valido. Ammessi: {', '.join(esecuzione.TRANSIZIONI)}")
    return esecuzione.elenco_viaggi(stato, data_da, data_a, limite, piano_id)


@router.get("/viaggi/{viaggio_id}")
def dettaglio_viaggio(viaggio_id: int) -> dict:
    """Viaggio con tappe, righe da consegnare e diario degli eventi."""
    return _esegui(lambda: esecuzione.dettaglio_viaggio(viaggio_id))


@router.post("/viaggi/{viaggio_id}/assegnazione")
def assegna(viaggio_id: int, dati: AssegnazioneInput) -> dict:
    """Assegna il viaggio a un mezzo aziendale oppure a un vettore terzo."""
    return _esegui(
        lambda: esecuzione.assegna(viaggio_id, dati.veicolo_id, dati.vettore_id, dati.autista)
    )


@router.post("/viaggi/{viaggio_id}/partenza")
def partenza(viaggio_id: int, dati: PartenzaInput | None = None) -> dict:
    """Registra la partenza: il viaggio passa in esecuzione."""
    return _esegui(lambda: esecuzione.registra_partenza(viaggio_id, (dati or PartenzaInput()).momento))


@router.post("/tappe/{tappa_id}/esito")
def esito_tappa(tappa_id: int, dati: EsitoTappaInput) -> dict:
    """Registra arrivo e quantità consegnate di una tappa."""
    return _esegui(
        lambda: esecuzione.registra_esito_tappa(
            tappa_id,
            dati.data_effettiva,
            dati.ora_effettiva,
            dati.quantita,
            dati.causale,
            dati.note,
            dati.non_eseguita,
        )
    )


@router.post("/viaggi/{viaggio_id}/chiusura")
def chiusura(viaggio_id: int, dati: ChiusuraViaggioInput | None = None) -> dict:
    """Chiude il viaggio con percorrenza e costo effettivi."""
    dati = dati or ChiusuraViaggioInput()
    return _esegui(
        lambda: esecuzione.chiudi_viaggio(viaggio_id, dati.km_effettivi, dati.costo_effettivo, dati.rientro)
    )


@router.post("/viaggi/{viaggio_id}/annullamento")
def annullamento(viaggio_id: int, dati: AnnullamentoInput) -> dict:
    """Annulla il viaggio e riporta i suoi ordini fra quelli da pianificare."""
    return _esegui(lambda: esecuzione.annulla_viaggio(viaggio_id, dati.motivo))


@router.get("/causali")
def causali() -> list[dict]:
    """Causali di mancato servizio utilizzabili sugli esiti delle tappe."""
    return [{"codice": c, "descrizione": d} for c, d in esecuzione.CAUSALI.items()]


@router.get("/kpi/otif")
def cruscotto_otif(
    data_da: str | None = None,
    data_a: str | None = None,
    tolleranza_minuti: float = Query(default=esecuzione.TOLLERANZA_RITARDO_MINUTI, ge=0, le=1440),
    tolleranza_quantita_pct: float = Query(default=esecuzione.TOLLERANZA_QUANTITA_PCT, ge=0, lt=1),
    accetta_anticipo: bool = True,
) -> dict:
    """OTIF a consuntivo con scomposizione per cliente, esecuzione e causale."""
    return otif.cruscotto_otif(
        data_da, data_a, tolleranza_minuti, tolleranza_quantita_pct, accetta_anticipo
    )


@router.get("/kpi/otif/ordini")
def otif_ordini(
    data_da: str | None = None,
    data_a: str | None = None,
    solo_mancati: bool = False,
    limite: int = Query(default=500, le=2000),
) -> list[dict]:
    """Esito di servizio ordine per ordine."""
    esiti = otif.dettaglio_ordini(data_da, data_a)
    if solo_mancati:
        esiti = [e for e in esiti if not e["otif"]]
    return esiti[:limite]


@router.get("/kpi/consuntivo")
def consuntivo(data_da: str | None = None, data_a: str | None = None) -> dict:
    """Costo pianificato contro costo effettivo dei viaggi chiusi."""
    return otif.consuntivo_costi(data_da, data_a)
