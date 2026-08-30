"""Modello di costo del trasporto per il mercato italiano.

Due logiche di costing coesistono, come in una vera direzione logistica:

* **Flotta propria (conto proprio)** - costo analitico per viaggio:
  carburante, pedaggi autostradali, costo del personale viaggiante,
  manutenzione/pneumatici e quota dei costi fissi giornalieri del mezzo.
* **Vettore terzo (conto terzi)** - listino a scaglioni peso/distanza
  tipico del groupage italiano, con minimo di fatturazione, supplemento
  carburante e supplementi per servizi accessori.

I valori di default sono parametri di configurazione: vanno allineati al
listino e ai costi reali dell'azienda dalla pagina Impostazioni.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Parametri di mercato (aggiornabili)
# --------------------------------------------------------------------------

PREZZO_GASOLIO_EUR_LITRO = 1.62
"""Prezzo medio gasolio alla pompa al netto IVA, rete extrarete Italia."""

KG_CO2_PER_LITRO_GASOLIO = 2.64
"""Fattore di emissione well-to-wheel semplificato del gasolio."""

SUPPLEMENTO_CARBURANTE_PCT = 0.06
"""Fuel surcharge medio applicato dai vettori sul netto merce."""


@dataclass(frozen=True)
class ProfiloVeicolo:
    """Parametri tecnico-economici di una tipologia di mezzo."""

    codice: str
    descrizione: str
    portata_kg: float
    volume_m3: float
    posti_pallet: int
    consumo_km_litro: float
    pedaggio_eur_km: float
    manutenzione_eur_km: float
    costo_fisso_giorno: float
    costo_autista_ora: float
    velocita_media_kmh: float = 60.0

    @property
    def costo_variabile_km(self) -> float:
        """Costo variabile per km (carburante + pedaggio + manutenzione)."""
        carburante = PREZZO_GASOLIO_EUR_LITRO / self.consumo_km_litro
        return round(carburante + self.pedaggio_eur_km + self.manutenzione_eur_km, 4)


# Profili standard della flotta italiana (portate e consumi indicativi).
PROFILI_VEICOLO: dict[str, ProfiloVeicolo] = {
    p.codice: p
    for p in [
        ProfiloVeicolo("FURGONE", "Furgone 35 q.li", 1200, 12.0, 4, 9.0, 0.05, 0.07, 38.0, 22.5, 55.0),
        ProfiloVeicolo("MOTRICE_75", "Motrice 75 q.li", 3500, 22.0, 8, 6.5, 0.10, 0.10, 58.0, 24.5, 58.0),
        ProfiloVeicolo("MOTRICE_180", "Motrice 18 t", 9500, 45.0, 16, 4.6, 0.15, 0.13, 92.0, 26.0, 62.0),
        ProfiloVeicolo("AUTOTRENO", "Autotreno 24 t", 15000, 75.0, 26, 3.6, 0.19, 0.16, 118.0, 27.5, 65.0),
        ProfiloVeicolo("BILICO", "Bilico 5 assi 13,6 m", 27000, 90.0, 33, 3.1, 0.22, 0.18, 135.0, 28.5, 68.0),
    ]
}

# Costo orario medio di una manovra di carico/scarico in stabilimento.
COSTO_SOSTA_ORA = 21.0
DURATA_SOSTA_BASE_ORE = 0.33
DURATA_SOSTA_PER_PALLET_ORE = 0.035


@dataclass
class DettaglioCosto:
    """Scomposizione del costo di un viaggio."""

    carburante: float = 0.0
    pedaggi: float = 0.0
    manutenzione: float = 0.0
    personale: float = 0.0
    costi_fissi: float = 0.0
    soste: float = 0.0
    traghetti: float = 0.0
    vettore: float = 0.0

    @property
    def totale(self) -> float:
        return round(
            self.carburante
            + self.pedaggi
            + self.manutenzione
            + self.personale
            + self.costi_fissi
            + self.soste
            + self.traghetti
            + self.vettore,
            2,
        )

    def as_dict(self) -> dict:
        return {
            "carburante": round(self.carburante, 2),
            "pedaggi": round(self.pedaggi, 2),
            "manutenzione": round(self.manutenzione, 2),
            "personale": round(self.personale, 2),
            "costi_fissi": round(self.costi_fissi, 2),
            "soste": round(self.soste, 2),
            "traghetti": round(self.traghetti, 2),
            "vettore": round(self.vettore, 2),
            "totale": self.totale,
        }


def durata_sosta_ore(pallet: float) -> float:
    """Tempo di carico/scarico stimato in funzione dei pallet movimentati."""
    return DURATA_SOSTA_BASE_ORE + DURATA_SOSTA_PER_PALLET_ORE * max(pallet, 0.0)


def costo_flotta_propria(
    profilo: ProfiloVeicolo,
    km: float,
    ore_guida: float,
    ore_sosta: float = 0.0,
    giorni_impegno: float = 1.0,
    costo_traghetti: float = 0.0,
) -> DettaglioCosto:
    """Costo analitico di un viaggio effettuato con mezzo aziendale."""
    litri = km / profilo.consumo_km_litro
    return DettaglioCosto(
        traghetti=costo_traghetti,
        carburante=litri * PREZZO_GASOLIO_EUR_LITRO,
        pedaggi=km * profilo.pedaggio_eur_km,
        manutenzione=km * profilo.manutenzione_eur_km,
        personale=(ore_guida + ore_sosta) * profilo.costo_autista_ora,
        costi_fissi=profilo.costo_fisso_giorno * giorni_impegno,
        soste=0.0,
    )


# --------------------------------------------------------------------------
# Listino conto terzi
# --------------------------------------------------------------------------

# Scaglioni di peso del groupage nazionale: (peso massimo kg, eur/100 kg).
# Il prezzo per quintale decresce al crescere del peso spedito.
SCAGLIONI_GROUPAGE: list[tuple[float, float]] = [
    (100, 22.0),
    (300, 16.5),
    (500, 13.8),
    (1000, 11.2),
    (2500, 9.1),
    (5000, 7.6),
    (float("inf"), 6.4),
]

# Coefficiente moltiplicativo per fascia di percorrenza in km.
COEFFICIENTE_DISTANZA: list[tuple[float, float]] = [
    (100, 0.62),
    (250, 0.80),
    (450, 1.00),
    (700, 1.24),
    (1000, 1.48),
    (float("inf"), 1.75),
]

SUPPLEMENTO_ISOLE_PCT = 0.22
"""Maggiorazione di listino per le destinazioni isolane (traghetto incluso)."""

MINIMO_FATTURABILE_EUR = 32.0
RAPPORTO_PESO_VOLUME = 250.0
"""Kg equivalenti per m3 (peso tassabile del groupage nazionale)."""


@dataclass
class TariffaVettore:
    """Listino di un vettore terzo, derivato dal listino base per sconto."""

    nome: str
    sconto_pct: float = 0.0
    minimo_fatturabile: float = MINIMO_FATTURABILE_EUR
    supplemento_carburante_pct: float = SUPPLEMENTO_CARBURANTE_PCT
    supplementi: dict[str, float] = field(default_factory=dict)


def peso_tassabile_kg(peso_kg: float, volume_m3: float) -> float:
    """Peso su cui si applica il listino: il maggiore fra reale e volumetrico."""
    return max(peso_kg, volume_m3 * RAPPORTO_PESO_VOLUME)


def _prezzo_quintale(peso: float) -> float:
    for soglia, prezzo in SCAGLIONI_GROUPAGE:
        if peso <= soglia:
            return prezzo
    return SCAGLIONI_GROUPAGE[-1][1]


def _coefficiente_distanza(km: float) -> float:
    for soglia, coeff in COEFFICIENTE_DISTANZA:
        if km <= soglia:
            return coeff
    return COEFFICIENTE_DISTANZA[-1][1]


def costo_vettore(
    peso_kg: float,
    volume_m3: float,
    km: float,
    tariffa: TariffaVettore | None = None,
    servizi: list[str] | None = None,
    isole: bool = False,
) -> DettaglioCosto:
    """Costo di una spedizione affidata a un vettore terzo.

    Con ``isole=True`` si applica la maggiorazione di listino prevista per
    Sicilia e Sardegna, che copre la traversata marittima.
    """
    tariffa = tariffa or TariffaVettore(nome="Listino base")
    peso = peso_tassabile_kg(peso_kg, volume_m3)
    netto = (peso / 100.0) * _prezzo_quintale(peso) * _coefficiente_distanza(km)
    netto *= 1 - tariffa.sconto_pct
    if isole:
        netto *= 1 + SUPPLEMENTO_ISOLE_PCT
    netto = max(netto, tariffa.minimo_fatturabile)
    netto *= 1 + tariffa.supplemento_carburante_pct
    for servizio in servizi or []:
        netto += tariffa.supplementi.get(servizio, 0.0)
    return DettaglioCosto(vettore=round(netto, 2))


def confronta_make_or_buy(
    profilo: ProfiloVeicolo,
    km: float,
    ore_guida: float,
    ore_sosta: float,
    peso_kg: float,
    volume_m3: float,
    tariffa: TariffaVettore | None = None,
    costo_traghetti: float = 0.0,
    isole: bool = False,
) -> dict:
    """Confronta conto proprio e conto terzi per la stessa spedizione."""
    proprio = costo_flotta_propria(profilo, km, ore_guida, ore_sosta, costo_traghetti=costo_traghetti)
    terzi = costo_vettore(peso_kg, volume_m3, km, tariffa, isole=isole)
    scelta = "PROPRIO" if proprio.totale <= terzi.totale else "TERZI"
    return {
        "conto_proprio": proprio.as_dict(),
        "conto_terzi": terzi.as_dict(),
        "scelta_consigliata": scelta,
        "risparmio_eur": round(abs(proprio.totale - terzi.totale), 2),
    }


def co2_kg(profilo: ProfiloVeicolo, km: float) -> float:
    """Emissioni di CO2 equivalente del viaggio, in kg."""
    return round(km / profilo.consumo_km_litro * KG_CO2_PER_LITRO_GASOLIO, 2)
