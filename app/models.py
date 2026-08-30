"""Schemi di input/output delle API (Pydantic v2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TipoSito = Literal["STABILIMENTO", "DEPOSITO", "CROSSDOCK", "CLIENTE", "FORNITORE"]
TipoOrdine = Literal["CLIENTE", "TRASFERIMENTO", "FORNITORE"]
StatoOrdine = Literal["DA_PIANIFICARE", "PIANIFICATO", "IN_TRANSITO", "CONSEGNATO", "ANNULLATO"]


class SitoInput(BaseModel):
    codice: str = Field(min_length=2, max_length=20)
    nome: str = Field(min_length=2)
    tipo: TipoSito
    indirizzo: str | None = None
    comune: str
    provincia: str = Field(min_length=2, max_length=2)
    cap: str | None = None
    regione: str | None = None
    lat: float = Field(ge=35.0, le=47.5, description="Latitudine (territorio italiano)")
    lon: float = Field(ge=6.0, le=19.0, description="Longitudine (territorio italiano)")
    capacita_pallet: int = 0
    apertura: float = Field(default=8.0, ge=0, le=24)
    chiusura: float = Field(default=18.0, ge=0, le=24)
    baie_carico: int = 1
    attivo: bool = True


class ArticoloInput(BaseModel):
    codice: str
    descrizione: str
    famiglia: str | None = None
    um: str = "PZ"
    peso_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)
    pezzi_per_pallet: float = Field(gt=0)
    valore_unitario: float = Field(ge=0)
    classe_abc: Literal["A", "B", "C"] = "C"
    adr: bool = False
    sovrapponibile: bool = True
    temperatura_controllata: bool = False
    sito_produttore: int | None = None


class GiacenzaInput(BaseModel):
    sito_id: int
    articolo_id: int
    quantita: float = Field(ge=0)
    impegnata: float = Field(default=0, ge=0)
    scorta_massima: float = Field(default=0, ge=0)
    domanda_media_giorno: float = Field(default=0, ge=0)
    deviazione_domanda: float = Field(default=0, ge=0)
    lead_time_giorni: float = Field(default=3, gt=0)
    deviazione_lead_time: float = Field(default=0.5, ge=0)
    livello_servizio: float = Field(default=0.95, gt=0, lt=1)


class RigaOrdineInput(BaseModel):
    articolo_id: int
    quantita: float = Field(gt=0)


class OrdineInput(BaseModel):
    riferimento: str | None = None
    tipo: TipoOrdine = "CLIENTE"
    origine_id: int
    destino_id: int
    data_richiesta: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    priorita: int = Field(default=5, ge=1, le=9)
    note: str | None = None
    righe: list[RigaOrdineInput] = Field(min_length=1)


class ParametriPianoInput(BaseModel):
    data_da: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    data_a: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    ora_partenza: float = Field(default=6.0, ge=0, le=23)
    soglia_groupage_pct: float = Field(default=55.0, ge=0, le=100)
    profilo_predefinito: str = "MOTRICE_180"
    sconto_vettore_pct: float = Field(default=0.12, ge=0, lt=1)
    salva: bool = False
    descrizione: str = ""


class SimulazioneMakeOrBuy(BaseModel):
    origine_id: int
    destino_id: int
    peso_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)
    pallet: float = Field(default=0, ge=0)
    profilo: str = "MOTRICE_180"
    sconto_vettore_pct: float = Field(default=0.12, ge=0, lt=1)
    andata_ritorno: bool = True
