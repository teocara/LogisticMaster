"""LogisticMaster - piattaforma di ottimizzazione logistica multi-sito.

Avvio: ``uvicorn app.main:app --reload`` oppure ``./run.sh``.
"""
from __future__ import annotations

import os

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import anagrafiche, kpi, pianificazione

CARTELLA_WEB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")

DESCRIZIONE = """
Piattaforma per l'ottimizzazione dei processi e dei flussi logistici di
aziende manifatturiere con piu' stabilimenti produttivi e piu' siti di
stoccaggio, calibrata sul mercato italiano.

**Moduli**

* anagrafiche di rete (stabilimenti, depositi, cross-dock, clienti);
* analisi delle scorte con scorta di sicurezza e punto di riordino;
* riequilibrio inter-sito delle giacenze;
* consolidamento dei carichi e scelta del mezzo;
* ottimizzazione dei giri di consegna con finestre orarie e Reg. CE 561/2006;
* costing conto proprio / conto terzi e cruscotto KPI.
"""

@asynccontextmanager
async def ciclo_di_vita(applicazione: FastAPI):
    """Crea lo schema al primo avvio e carica lo scenario se il DB e' vuoto."""
    db.inizializza()
    if not db.query_uno("SELECT id FROM siti LIMIT 1"):
        from .seed import popola

        popola()
    yield


app = FastAPI(
    title="LogisticMaster",
    lifespan=ciclo_di_vita,
    description=DESCRIZIONE,
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.include_router(anagrafiche.router)
app.include_router(pianificazione.router)
app.include_router(kpi.router)


@app.get("/api/stato", tags=["sistema"])
def stato() -> dict:
    """Stato di salute della piattaforma e consistenza dei dati."""
    conteggi = {
        tabella: db.query_uno(f"SELECT COUNT(*) AS n FROM {tabella}")["n"]
        for tabella in ("siti", "articoli", "giacenze", "ordini", "veicoli", "vettori", "piani")
    }
    return {"stato": "operativo", "versione": app.version, "conteggi": conteggi}


@app.post("/api/admin/ricarica-demo", tags=["sistema"])
def ricarica_demo() -> dict:
    """Ripristina lo scenario dimostrativo (cancella i dati esistenti)."""
    from .seed import popola

    return {"esito": "scenario ricaricato", "conteggi": popola()}


app.mount("/static", StaticFiles(directory=CARTELLA_WEB), name="static")


@app.get("/", include_in_schema=False)
def interfaccia() -> FileResponse:
    return FileResponse(os.path.join(CARTELLA_WEB, "index.html"))
