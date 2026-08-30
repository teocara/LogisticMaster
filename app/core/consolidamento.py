"""Costruzione unita' di carico e consolidamento delle spedizioni.

Trasforma le righe d'ordine in pallet (rispettando pezzi per pallet e
sovrapponibilita'), aggrega le spedizioni compatibili verso la stessa
destinazione e assegna a ogni carico il mezzo piu' economico in grado di
trasportarlo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .costi import PROFILI_VEICOLO, ProfiloVeicolo

# Dimensioni standard EPAL usate per il calcolo dei posti pallet.
ALTEZZA_UTILE_MEZZO_CM = 240.0
ALTEZZA_PALLET_CM = 15.0


@dataclass
class RigaCarico:
    """Riga di ordine gia' convertita in dati fisici."""

    ordine_id: int
    articolo_id: int
    quantita: float
    peso_kg: float
    volume_m3: float
    pallet: float
    adr: bool = False
    sovrapponibile: bool = True
    temperatura_controllata: bool = False


@dataclass
class Spedizione:
    """Merce da portare da un'origine a una destinazione entro una data."""

    id: str
    origine_id: int
    destino_id: int
    data_richiesta: str
    priorita: int = 5
    righe: list[RigaCarico] = field(default_factory=list)
    finestra_apertura: float = 8.0
    finestra_chiusura: float = 18.0

    @property
    def peso_kg(self) -> float:
        return round(sum(r.peso_kg for r in self.righe), 2)

    @property
    def volume_m3(self) -> float:
        return round(sum(r.volume_m3 for r in self.righe), 3)

    @property
    def pallet(self) -> float:
        return round(sum(r.pallet for r in self.righe), 2)

    @property
    def adr(self) -> bool:
        return any(r.adr for r in self.righe)

    @property
    def temperatura_controllata(self) -> bool:
        return any(r.temperatura_controllata for r in self.righe)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "origine_id": self.origine_id,
            "destino_id": self.destino_id,
            "data_richiesta": self.data_richiesta,
            "priorita": self.priorita,
            "peso_kg": self.peso_kg,
            "volume_m3": self.volume_m3,
            "pallet": self.pallet,
            "adr": self.adr,
            "righe": len(self.righe),
        }


def pallet_necessari(
    quantita: float, pezzi_per_pallet: float, sovrapponibile: bool = True
) -> float:
    """Posti pallet occupati da una quantita' di pezzi.

    La merce non sovrapponibile occupa sempre un posto pallet intero;
    quella sovrapponibile puo' condividere il posto in altezza (fino a due
    piani), quindi conta mezzo posto per pallet fisico.
    """
    if pezzi_per_pallet <= 0:
        return 0.0
    pallet_fisici = math.ceil(quantita / pezzi_per_pallet)
    if sovrapponibile:
        piani = max(int(ALTEZZA_UTILE_MEZZO_CM // (ALTEZZA_PALLET_CM + 100.0)), 1)
        piani = min(piani, 2)
        return pallet_fisici / piani
    return float(pallet_fisici)


@dataclass
class Carico:
    """Insieme di spedizioni assegnate a un singolo mezzo."""

    id: str
    origine_id: int
    profilo: ProfiloVeicolo
    spedizioni: list[Spedizione] = field(default_factory=list)

    @property
    def peso_kg(self) -> float:
        return round(sum(s.peso_kg for s in self.spedizioni), 2)

    @property
    def volume_m3(self) -> float:
        return round(sum(s.volume_m3 for s in self.spedizioni), 3)

    @property
    def pallet(self) -> float:
        return round(sum(s.pallet for s in self.spedizioni), 2)

    @property
    def destinazioni(self) -> list[int]:
        return sorted({s.destino_id for s in self.spedizioni})

    def saturazione(self) -> dict:
        """Saturazione del mezzo su peso, volume e posti pallet."""
        peso = self.peso_kg / self.profilo.portata_kg if self.profilo.portata_kg else 0
        volume = self.volume_m3 / self.profilo.volume_m3 if self.profilo.volume_m3 else 0
        pallet = self.pallet / self.profilo.posti_pallet if self.profilo.posti_pallet else 0
        return {
            "peso_pct": round(peso * 100, 1),
            "volume_pct": round(volume * 100, 1),
            "pallet_pct": round(pallet * 100, 1),
            "vincolante": max(
                (("peso", peso), ("volume", volume), ("pallet", pallet)),
                key=lambda x: x[1],
            )[0],
            "saturazione_pct": round(max(peso, volume, pallet) * 100, 1),
        }

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "origine_id": self.origine_id,
            "veicolo": self.profilo.codice,
            "veicolo_descrizione": self.profilo.descrizione,
            "peso_kg": self.peso_kg,
            "volume_m3": self.volume_m3,
            "pallet": self.pallet,
            "destinazioni": self.destinazioni,
            "spedizioni": [s.as_dict() for s in self.spedizioni],
            "saturazione": self.saturazione(),
        }


def _entra(profilo: ProfiloVeicolo, peso: float, volume: float, pallet: float) -> bool:
    return (
        peso <= profilo.portata_kg + 1e-6
        and volume <= profilo.volume_m3 + 1e-6
        and pallet <= profilo.posti_pallet + 1e-6
    )


def scegli_veicolo(
    peso: float, volume: float, pallet: float, profili: list[ProfiloVeicolo] | None = None
) -> ProfiloVeicolo:
    """Mezzo piu' piccolo (e quindi meno costoso) capace di contenere il carico."""
    candidati = sorted(
        profili or PROFILI_VEICOLO.values(), key=lambda p: (p.portata_kg, p.volume_m3)
    )
    for profilo in candidati:
        if _entra(profilo, peso, volume, pallet):
            return profilo
    return candidati[-1]


def consolida(
    spedizioni: list[Spedizione],
    profili: list[ProfiloVeicolo] | None = None,
    saturazione_obiettivo: float = 0.85,
) -> list[Carico]:
    """Raggruppa le spedizioni in carichi per origine e data.

    Le spedizioni sono ordinate per volume decrescente (first-fit
    decreasing) e inserite nel primo carico compatibile; ADR e merce a
    temperatura controllata non vengono mai mescolate con merce ordinaria.
    """
    profili_disponibili = sorted(
        profili or PROFILI_VEICOLO.values(), key=lambda p: (p.portata_kg, p.volume_m3)
    )
    mezzo_massimo = profili_disponibili[-1]
    carichi: list[Carico] = []

    gruppi: dict[tuple[int, str, bool, bool], list[Spedizione]] = {}
    for s in spedizioni:
        chiave = (s.origine_id, s.data_richiesta, s.adr, s.temperatura_controllata)
        gruppi.setdefault(chiave, []).append(s)

    contatore = 1
    for (origine_id, data, _adr, _temp), gruppo in sorted(gruppi.items(), key=lambda x: str(x[0])):
        gruppo.sort(key=lambda s: (-s.pallet, -s.peso_kg))
        aperti: list[Carico] = []
        for sped in gruppo:
            inserita = False
            for carico in aperti:
                peso = carico.peso_kg + sped.peso_kg
                volume = carico.volume_m3 + sped.volume_m3
                pallet = carico.pallet + sped.pallet
                if _entra(mezzo_massimo, peso, volume, pallet):
                    carico.spedizioni.append(sped)
                    inserita = True
                    break
            if not inserita:
                aperti.append(
                    Carico(
                        id=f"CAR{contatore:04d}",
                        origine_id=origine_id,
                        profilo=mezzo_massimo,
                        spedizioni=[sped],
                    )
                )
                contatore += 1
        # Ridimensiona ogni carico sul mezzo minimo sufficiente.
        for carico in aperti:
            carico.profilo = scegli_veicolo(
                carico.peso_kg, carico.volume_m3, carico.pallet, profili_disponibili
            )
        carichi.extend(aperti)

    return carichi


def carichi_sottosaturi(carichi: list[Carico], soglia_pct: float = 65.0) -> list[Carico]:
    """Carichi la cui saturazione resta sotto la soglia: candidati a groupage."""
    return [c for c in carichi if c.saturazione()["saturazione_pct"] < soglia_pct]
