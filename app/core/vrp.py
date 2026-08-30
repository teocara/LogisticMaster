"""Ottimizzazione dei giri di consegna (VRP con capacita' e finestre orarie).

Algoritmo in due fasi:

1. **Clarke & Wright** (savings paralleli) costruisce i giri fondendo le
   coppie di fermate che fanno risparmiare piu' chilometri, purche' la
   fusione resti compatibile con la capacita' del mezzo, con le finestre
   orarie dei clienti e con i limiti di guida del Reg. CE 561/2006.
2. **2-opt** riordina le fermate all'interno di ogni giro finche' non si
   trovano piu' miglioramenti ammissibili.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .costi import (
    PROFILI_VEICOLO,
    DettaglioCosto,
    ProfiloVeicolo,
    co2_kg,
    costo_flotta_propria,
    durata_sosta_ore,
)
from .geo import MatriceDistanze

# Limiti di guida per il singolo autista (Reg. CE 561/2006).
MAX_ORE_GUIDA_GIORNO = 9.0
MAX_ORE_GUIDA_CONTINUATE = 4.5
PAUSA_OBBLIGATORIA_ORE = 0.75
MAX_ORE_SERVIZIO_GIORNO = 13.0


@dataclass
class Fermata:
    """Punto di consegna con i suoi vincoli."""

    id: str
    sito_id: int
    peso_kg: float
    volume_m3: float
    pallet: float
    apertura: float = 8.0
    chiusura: float = 18.0
    priorita: int = 5
    spedizioni: list[str] = field(default_factory=list)


@dataclass
class Giro:
    """Giro di consegna assegnato a un mezzo."""

    id: str
    deposito_id: int
    profilo: ProfiloVeicolo
    fermate: list[Fermata] = field(default_factory=list)
    ora_partenza: float = 6.0
    km: float = 0.0
    ore_guida: float = 0.0
    ore_sosta: float = 0.0
    ore_attesa: float = 0.0
    pause: float = 0.0
    ore_traghetto: float = 0.0
    costo: DettaglioCosto = field(default_factory=DettaglioCosto)
    cronoprogramma: list[dict] = field(default_factory=list)
    violazioni: list[str] = field(default_factory=list)
    giorni_impegno: float = 1.0

    @property
    def ammissibile(self) -> bool:
        return not self.violazioni

    @property
    def peso_kg(self) -> float:
        return round(sum(f.peso_kg for f in self.fermate), 2)

    @property
    def volume_m3(self) -> float:
        return round(sum(f.volume_m3 for f in self.fermate), 3)

    @property
    def pallet(self) -> float:
        return round(sum(f.pallet for f in self.fermate), 2)

    @property
    def durata_ore(self) -> float:
        return round(
            self.ore_guida + self.ore_sosta + self.ore_attesa + self.pause + self.ore_traghetto, 2
        )

    def saturazione_pct(self) -> float:
        valori = [
            self.peso_kg / self.profilo.portata_kg if self.profilo.portata_kg else 0,
            self.volume_m3 / self.profilo.volume_m3 if self.profilo.volume_m3 else 0,
            self.pallet / self.profilo.posti_pallet if self.profilo.posti_pallet else 0,
        ]
        return round(max(valori) * 100, 1)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "deposito_id": self.deposito_id,
            "veicolo": self.profilo.codice,
            "veicolo_descrizione": self.profilo.descrizione,
            "sequenza": [f.sito_id for f in self.fermate],
            "fermate": [
                {
                    "id": f.id,
                    "sito_id": f.sito_id,
                    "peso_kg": round(f.peso_kg, 1),
                    "pallet": round(f.pallet, 2),
                    "finestra": [f.apertura, f.chiusura],
                    "spedizioni": f.spedizioni,
                }
                for f in self.fermate
            ],
            "km": round(self.km, 1),
            "ore_guida": round(self.ore_guida, 2),
            "ore_sosta": round(self.ore_sosta, 2),
            "ore_attesa": round(self.ore_attesa, 2),
            "pause": round(self.pause, 2),
            "ore_traghetto": round(self.ore_traghetto, 2),
            "durata_ore": self.durata_ore,
            "peso_kg": self.peso_kg,
            "volume_m3": self.volume_m3,
            "pallet": self.pallet,
            "saturazione_pct": self.saturazione_pct(),
            "costo": self.costo.as_dict(),
            "costo_per_km": round(self.costo.totale / self.km, 3) if self.km else 0.0,
            "co2_kg": co2_kg(self.profilo, self.km),
            "giorni_impegno": self.giorni_impegno,
            "ammissibile": self.ammissibile,
            "violazioni": self.violazioni,
            "cronoprogramma": self.cronoprogramma,
        }


class _StatoGuida:
    """Stato dell'autista durante la simulazione di un giro.

    Tiene il tempo di guida giornaliero, la guida continuata (per le pause
    obbligatorie) e il giorno di calendario, cosi' che un viaggio a lunga
    percorrenza venga pianificato su piu' giorni invece di essere
    dichiarato inammissibile.
    """

    def __init__(self, ora_partenza: float):
        self.ora_partenza = ora_partenza
        self.orologio = ora_partenza      # ora del giorno
        self.giorno = 1
        self.guida_giorno = 0.0
        self.servizio_giorno = 0.0
        self.guida_continuata = 0.0
        self.ore_guida = 0.0
        self.ore_sosta = 0.0
        self.ore_attesa = 0.0
        self.ore_pausa = 0.0
        self.ore_traghetto = 0.0

    # -- avanzamenti elementari -------------------------------------------
    def riposo_giornaliero(self) -> None:
        """Chiude la giornata e riparte il mattino successivo."""
        self.giorno += 1
        self.orologio = self.ora_partenza
        self.guida_giorno = 0.0
        self.servizio_giorno = 0.0
        self.guida_continuata = 0.0

    def pausa(self) -> None:
        """Pausa obbligatoria dopo 4,5 ore di guida continuata."""
        self.orologio += PAUSA_OBBLIGATORIA_ORE
        self.servizio_giorno += PAUSA_OBBLIGATORIA_ORE
        self.ore_pausa += PAUSA_OBBLIGATORIA_ORE
        self.guida_continuata = 0.0

    def guida(self, ore: float) -> None:
        """Percorre le ore di guida indicate, inserendo pause e riposi."""
        residuo = ore
        while residuo > 1e-6:
            if self.guida_continuata >= MAX_ORE_GUIDA_CONTINUATE - 1e-6:
                self.pausa()
            margine = min(
                MAX_ORE_GUIDA_GIORNO - self.guida_giorno,
                MAX_ORE_SERVIZIO_GIORNO - self.servizio_giorno,
                MAX_ORE_GUIDA_CONTINUATE - self.guida_continuata,
            )
            if margine <= 1e-6:
                self.riposo_giornaliero()
                continue
            quota = min(residuo, margine)
            self.orologio += quota
            self.guida_giorno += quota
            self.servizio_giorno += quota
            self.guida_continuata += quota
            self.ore_guida += quota
            residuo -= quota

    def traversata(self, ore: float) -> None:
        """Traversata in traghetto: tempo di riposo, non di guida."""
        self.orologio += ore
        self.ore_traghetto += ore
        self.guida_continuata = 0.0
        if ore >= 9.0:
            # Una traversata lunga vale come riposo giornaliero.
            self.guida_giorno = 0.0
            self.servizio_giorno = 0.0
        if self.orologio >= 24.0:
            self.giorno += int(self.orologio // 24)
            self.orologio %= 24.0

    def attendi_finestra(self, apertura: float, chiusura: float) -> None:
        """Attende l'apertura del sito, rinviando al giorno dopo se serve."""
        if self.orologio > chiusura:
            self.riposo_giornaliero()
        if self.orologio < apertura:
            attesa = apertura - self.orologio
            self.ore_attesa += attesa
            self.servizio_giorno += attesa
            self.orologio = apertura

    def servi(self, ore: float) -> None:
        self.orologio += ore
        self.servizio_giorno += ore
        self.ore_sosta += ore


def simula_giro(
    deposito_id: int,
    fermate: list[Fermata],
    matrice: MatriceDistanze,
    ora_partenza: float = 6.0,
) -> dict | None:
    """Simula il giro rispettando finestre orarie e Reg. CE 561/2006.

    La simulazione pianifica pause e riposi giornalieri: un giro puo'
    quindi durare piu' giorni. Le anomalie residue (finestra oraria del
    sito piu' breve del tempo di scarico) sono elencate in ``violazioni``.
    Restituisce None solo se non ci sono fermate.
    """
    if not fermate:
        return None

    stato = _StatoGuida(ora_partenza)
    posizione = deposito_id
    km = costo_traghetti = 0.0
    crono: list[dict] = []
    violazioni: list[str] = []

    def percorri(verso: int) -> None:
        nonlocal km, costo_traghetti, posizione
        km += matrice.km(posizione, verso)
        traghetto = matrice.traghetto(posizione, verso)
        if traghetto:
            costo_traghetti += traghetto["costo_eur"]
            stato.traversata(traghetto["ore"])
        stato.guida(matrice.ore_guida(posizione, verso))
        posizione = verso

    for fermata in fermate:
        percorri(fermata.sito_id)
        stato.attendi_finestra(fermata.apertura, fermata.chiusura)
        servizio = durata_sosta_ore(fermata.pallet)
        if stato.orologio + servizio > fermata.chiusura + 1e-6:
            violazioni.append(
                f"il sito {fermata.sito_id} chiude alle {fermata.chiusura:.2f}: "
                f"finestra insufficiente per {servizio:.2f} h di scarico"
            )
        crono.append(
            {
                "sito_id": fermata.sito_id,
                "giorno": stato.giorno,
                "arrivo": round(stato.orologio, 2),
                "partenza": round(stato.orologio + servizio, 2),
                "km_progressivi": round(km, 1),
            }
        )
        stato.servi(servizio)

    percorri(deposito_id)
    crono.append(
        {
            "sito_id": deposito_id,
            "giorno": stato.giorno,
            "arrivo": round(stato.orologio, 2),
            "partenza": None,
            "km_progressivi": round(km, 1),
        }
    )

    return {
        "km": km,
        "ore_guida": stato.ore_guida,
        "ore_sosta": stato.ore_sosta,
        "ore_attesa": stato.ore_attesa,
        "pause": stato.ore_pausa,
        "ore_traghetto": round(stato.ore_traghetto, 2),
        "costo_traghetti": round(costo_traghetti, 2),
        "cronoprogramma": crono,
        "violazioni": violazioni,
        "ammissibile": not violazioni,
        "giorni_impegno": float(stato.giorno),
    }


def _capacita_ok(profilo: ProfiloVeicolo, fermate: list[Fermata]) -> bool:
    peso = sum(f.peso_kg for f in fermate)
    volume = sum(f.volume_m3 for f in fermate)
    pallet = sum(f.pallet for f in fermate)
    return (
        peso <= profilo.portata_kg + 1e-6
        and volume <= profilo.volume_m3 + 1e-6
        and pallet <= profilo.posti_pallet + 1e-6
    )


def _giorni(
    fermate: list[Fermata], deposito_id: int, matrice: MatriceDistanze, ora_partenza: float
) -> float:
    """Giornate necessarie a un insieme di fermate servite come unico giro."""
    simulazione = simula_giro(deposito_id, fermate, matrice, ora_partenza)
    return simulazione["giorni_impegno"] if simulazione else 1.0


def _due_opt(
    deposito_id: int,
    fermate: list[Fermata],
    matrice: MatriceDistanze,
    ora_partenza: float,
) -> tuple[list[Fermata], dict]:
    """Miglioramento 2-opt vincolato all'ammissibilita' del giro."""
    migliore = list(fermate)
    simulazione = simula_giro(deposito_id, migliore, matrice, ora_partenza)
    if simulazione is None:
        return migliore, {}
    migliorato = True
    while migliorato and len(migliore) > 2:
        migliorato = False
        for i in range(len(migliore) - 1):
            for j in range(i + 1, len(migliore)):
                candidato = migliore[:i] + migliore[i : j + 1][::-1] + migliore[j + 1 :]
                prova = simula_giro(deposito_id, candidato, matrice, ora_partenza)
                if prova is None or prova["km"] >= simulazione["km"] - 1e-6:
                    continue
                # Non si accetta uno scambio che rende inammissibile un
                # giro che prima rispettava tutti i vincoli.
                if simulazione["ammissibile"] and not prova["ammissibile"]:
                    continue
                migliore, simulazione = candidato, prova
                migliorato = True
    return migliore, simulazione


def ottimizza_giri(
    deposito_id: int,
    fermate: list[Fermata],
    matrice: MatriceDistanze,
    profilo: ProfiloVeicolo | None = None,
    ora_partenza: float = 6.0,
    max_veicoli: int | None = None,
    max_giorni: float = 3.0,
    prefisso: str = "GIRO",
) -> list[Giro]:
    """Costruisce i giri ottimizzati per un deposito.

    Restituisce i giri gia' valorizzati (km, tempi, costo, CO2). Le
    fermate non collocabili in alcun giro ammissibile vengono servite con
    giri dedicati.
    """
    profilo = profilo or PROFILI_VEICOLO["MOTRICE_180"]
    if not fermate:
        return []

    # Fase 1: un giro per fermata.
    rotte: list[list[Fermata]] = [[f] for f in fermate]

    # Fase 2: savings di Clarke & Wright.
    savings: list[tuple[float, int, int]] = []
    for i, a in enumerate(fermate):
        for b in fermate[i + 1 :]:
            s = (
                matrice.km(deposito_id, a.sito_id)
                + matrice.km(deposito_id, b.sito_id)
                - matrice.km(a.sito_id, b.sito_id)
            )
            savings.append((s, fermate.index(a), fermate.index(b)))
    savings.sort(reverse=True)

    def rotta_di(indice: int) -> list[Fermata] | None:
        for rotta in rotte:
            if fermate[indice] in rotta:
                return rotta
        return None

    for _s, ia, ib in savings:
        ra, rb = rotta_di(ia), rotta_di(ib)
        if ra is None or rb is None or ra is rb:
            continue
        # Si fondono solo estremita' di rotta (vincolo di Clarke & Wright).
        a, b = fermate[ia], fermate[ib]
        combinazioni = []
        if ra[-1] is a and rb[0] is b:
            combinazioni.append(ra + rb)
        if rb[-1] is b and ra[0] is a:
            combinazioni.append(rb + ra)
        if ra[-1] is a and rb[-1] is b:
            combinazioni.append(ra + rb[::-1])
        if ra[0] is a and rb[0] is b:
            combinazioni.append(ra[::-1] + rb)
        giorni_a = _giorni(ra, deposito_id, matrice, ora_partenza)
        giorni_b = _giorni(rb, deposito_id, matrice, ora_partenza)
        for candidato in combinazioni:
            if not _capacita_ok(profilo, candidato):
                continue
            prova = simula_giro(deposito_id, candidato, matrice, ora_partenza)
            if prova is None or not prova["ammissibile"]:
                continue
            # La fusione non deve allungare il giro di ulteriori giornate:
            # consolidare non puo' peggiorare il livello di servizio.
            if prova["giorni_impegno"] > max(giorni_a, giorni_b, 1) or prova["giorni_impegno"] > max_giorni:
                continue
            rotte.remove(ra)
            rotte.remove(rb)
            rotte.append(candidato)
            break

    if max_veicoli is not None and len(rotte) > max_veicoli:
        rotte.sort(key=lambda r: sum(f.pallet for f in r), reverse=True)

    giri: list[Giro] = []
    for indice, rotta in enumerate(rotte, start=1):
        sequenza, simulazione = _due_opt(deposito_id, rotta, matrice, ora_partenza)
        giro = Giro(
            id=f"{prefisso}{indice:03d}",
            deposito_id=deposito_id,
            profilo=profilo,
            fermate=sequenza,
            ora_partenza=ora_partenza,
            km=simulazione["km"],
            ore_guida=simulazione["ore_guida"],
            ore_sosta=simulazione["ore_sosta"],
            ore_attesa=simulazione["ore_attesa"],
            pause=simulazione["pause"],
            ore_traghetto=simulazione["ore_traghetto"],
            cronoprogramma=simulazione["cronoprogramma"],
            violazioni=simulazione["violazioni"],
            giorni_impegno=simulazione["giorni_impegno"],
        )
        giro.costo = costo_flotta_propria(
            profilo,
            giro.km,
            giro.ore_guida + giro.pause,
            giro.ore_sosta + giro.ore_attesa,
            giorni_impegno=giro.giorni_impegno,
            costo_traghetti=simulazione["costo_traghetti"],
        )
        giri.append(giro)

    giri.sort(key=lambda g: -g.km)
    for indice, giro in enumerate(giri, start=1):
        giro.id = f"{prefisso}{indice:03d}"
    return giri
