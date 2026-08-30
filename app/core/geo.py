"""Calcoli geografici e matrice delle distanze stradali.

Il motore non dipende da servizi esterni di routing: la distanza stradale
viene stimata dalla distanza ortodromica (haversine) corretta con un
fattore di tortuosita' calibrato sulla rete viaria italiana e con una
penalizzazione per gli attraversamenti appenninici/alpini.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Fattore medio di tortuosita' della rete stradale italiana:
# rapporto fra km percorsi su strada e distanza in linea d'aria.
FATTORE_TORTUOSITA = 1.14

# Correzione aggiuntiva per tratte che attraversano la dorsale appenninica
# o l'arco alpino (percorsi piu' lunghi e piu' lenti).
FATTORE_OROGRAFICO = 1.05

# Velocita' commerciali medie (km/h) per fascia di percorrenza.
# Tratte brevi = distribuzione urbana, tratte lunghe = autostrada.
VELOCITA_PER_FASCIA = (
    (30.0, 38.0),    # fino a 30 km: urbano / extraurbano congestionato
    (80.0, 52.0),    # fino a 80 km: statali e superstrade
    (250.0, 68.0),   # fino a 250 km: autostrada con tratti misti
    (float("inf"), 76.0),  # oltre: autostrada
)

RAGGIO_TERRA_KM = 6371.0088

# --------------------------------------------------------------------------
# Collegamenti marittimi
# --------------------------------------------------------------------------
# Senza il traghetto le relazioni con Sicilia e Sardegna risultano piu'
# brevi e piu' economiche di quanto siano nella realta'. I porti sono
# quelli effettivamente usati dal traffico merci.

PORTI_CONTINENTE = {
    "Genova": (44.4100, 8.9300),
    "Livorno": (43.5500, 10.3100),
    "Civitavecchia": (42.0900, 11.7900),
    "Napoli": (40.8400, 14.2500),
    "Villa San Giovanni": (38.2200, 15.6400),
}
PORTI_SARDEGNA = {
    "Porto Torres": (40.8400, 8.4000),
    "Olbia": (40.9200, 9.5000),
    "Cagliari": (39.2000, 9.1100),
}
PORTO_SICILIA = ("Messina", 38.1900, 15.5600)

VELOCITA_TRAGHETTO_KMH = 33.0
ORE_IMBARCO_SBARCO = 2.0
"""Attesa media fra accettazione, imbarco e sbarco di un mezzo pesante."""

COSTO_FISSO_TRAGHETTO = 210.0
COSTO_TRAGHETTO_EUR_KM = 1.15
"""Tariffa indicativa per metro lineare/mezzo pesante, ricondotta ai km di navigazione."""

# Attraversamento dello Stretto di Messina: traversata breve ma con attesa.
ORE_STRETTO = 1.4
COSTO_STRETTO = 68.0


@dataclass(frozen=True)
class Punto:
    """Coordinata geografica con identificativo."""

    id: int
    lat: float
    lon: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza ortodromica in km fra due coordinate WGS84."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * RAGGIO_TERRA_KM * math.asin(math.sqrt(a))


def _attraversa_dorsale(lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
    """Euristica: la tratta attraversa Appennini o Alpi.

    Vero se i due punti stanno su versanti opposti rispetto alla dorsale
    appenninica approssimata, oppure se la tratta supera il 45.7 parallelo
    con una componente est-ovest rilevante (arco alpino).
    """
    # Dorsale appenninica approssimata da una retta lon = f(lat).
    def versante(lat: float, lon: float) -> int:
        lon_dorsale = 0.95 * lat - 30.6
        return 1 if lon > lon_dorsale else -1

    if versante(lat1, lon1) != versante(lat2, lon2):
        return True
    if max(lat1, lat2) > 45.7 and abs(lon1 - lon2) > 1.5:
        return True
    return False


def isola(lat: float, lon: float) -> str | None:
    """Restituisce SICILIA, SARDEGNA o None per una coordinata italiana."""
    if 36.6 <= lat <= 38.35 and 12.3 <= lon <= 15.7:
        return "SICILIA"
    if 38.8 <= lat <= 41.3 and 8.1 <= lon <= 9.9:
        return "SARDEGNA"
    return None


def _porto_piu_vicino(lat: float, lon: float, porti: dict[str, tuple[float, float]]) -> tuple[str, float, float]:
    nome = min(porti, key=lambda n: haversine_km(lat, lon, *porti[n]))
    return (nome, *porti[nome])


def collegamento_marittimo(a: Punto, b: Punto) -> dict | None:
    """Traghetto necessario per la relazione, con km e ore di navigazione.

    Restituisce None se la relazione e' interamente stradale (compresi i
    collegamenti interni alla stessa isola).
    """
    isola_a, isola_b = isola(a.lat, a.lon), isola(b.lat, b.lon)
    if isola_a == isola_b:
        return None

    if "SARDEGNA" in (isola_a, isola_b):
        sardo, continentale = (a, b) if isola_a == "SARDEGNA" else (b, a)
        nome_sardo, lat_s, lon_s = _porto_piu_vicino(sardo.lat, sardo.lon, PORTI_SARDEGNA)
        nome_cont, lat_c, lon_c = _porto_piu_vicino(
            continentale.lat, continentale.lon, {k: v for k, v in PORTI_CONTINENTE.items() if k != "Villa San Giovanni"}
        )
        km_mare = haversine_km(lat_s, lon_s, lat_c, lon_c)
        return {
            "tratta": f"{nome_cont} - {nome_sardo}",
            "km_mare": round(km_mare, 1),
            "ore": round(km_mare / VELOCITA_TRAGHETTO_KMH + ORE_IMBARCO_SBARCO, 2),
            "costo_eur": round(COSTO_FISSO_TRAGHETTO + COSTO_TRAGHETTO_EUR_KM * km_mare, 2),
            "porto_continente": (lat_c, lon_c),
            "porto_isola": (lat_s, lon_s),
        }

    # Sicilia: attraversamento dello Stretto di Messina.
    return {
        "tratta": "Villa San Giovanni - Messina",
        "km_mare": 12.0,
        "ore": ORE_STRETTO,
        "costo_eur": COSTO_STRETTO,
        "porto_continente": PORTI_CONTINENTE["Villa San Giovanni"],
        "porto_isola": (PORTO_SICILIA[1], PORTO_SICILIA[2]),
    }


def distanza_stradale_km(a: Punto, b: Punto) -> float:
    """Stima della distanza stradale in km fra due punti."""
    if a.id == b.id:
        return 0.0

    marittimo = collegamento_marittimo(a, b)
    if marittimo and marittimo["km_mare"] > 50:
        # Con una traversata lunga la strada arriva al porto e riprende
        # dall'altro lato: la distanza in linea d'aria non e' percorribile.
        lat_c, lon_c = marittimo["porto_continente"]
        lat_i, lon_i = marittimo["porto_isola"]
        if isola(a.lat, a.lon):
            avvicinamento = _km_terrestri(a.lat, a.lon, lat_i, lon_i) + _km_terrestri(lat_c, lon_c, b.lat, b.lon)
        else:
            avvicinamento = _km_terrestri(a.lat, a.lon, lat_c, lon_c) + _km_terrestri(lat_i, lon_i, b.lat, b.lon)
        return round(avvicinamento, 2)

    return round(_km_terrestri(a.lat, a.lon, b.lat, b.lon), 2)


def _km_terrestri(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza stradale pura, senza considerare i collegamenti marittimi."""
    base = haversine_km(lat1, lon1, lat2, lon2) * FATTORE_TORTUOSITA
    if _attraversa_dorsale(lat1, lon1, lat2, lon2):
        base *= FATTORE_OROGRAFICO
    return base


def tempo_percorrenza_ore(km: float) -> float:
    """Tempo di guida stimato in ore per una percorrenza in km."""
    for soglia, velocita in VELOCITA_PER_FASCIA:
        if km <= soglia:
            return km / velocita
    return km / VELOCITA_PER_FASCIA[-1][1]


class MatriceDistanze:
    """Matrice simmetrica di distanze e tempi fra un insieme di punti."""

    def __init__(self, punti: list[Punto]):
        self.punti = {p.id: p for p in punti}
        self._km: dict[tuple[int, int], float] = {}
        self._ore: dict[tuple[int, int], float] = {}
        self._ore_guida: dict[tuple[int, int], float] = {}
        self._traghetti: dict[tuple[int, int], dict] = {}
        ids = list(self.punti)
        for i, a in enumerate(ids):
            for b in ids[i:]:
                km = distanza_stradale_km(self.punti[a], self.punti[b])
                ore = ore_guida = tempo_percorrenza_ore(km)
                traghetto = collegamento_marittimo(self.punti[a], self.punti[b])
                if traghetto:
                    ore += traghetto["ore"]
                    self._traghetti[(a, b)] = self._traghetti[(b, a)] = traghetto
                self._km[(a, b)] = self._km[(b, a)] = km
                self._ore[(a, b)] = self._ore[(b, a)] = ore
                self._ore_guida[(a, b)] = self._ore_guida[(b, a)] = ore_guida

    def km(self, a: int, b: int) -> float:
        return self._km[(a, b)]

    def ore(self, a: int, b: int) -> float:
        """Tempo totale della tratta, traversata marittima inclusa."""
        return self._ore[(a, b)]

    def ore_guida(self, a: int, b: int) -> float:
        """Sole ore di guida della tratta: la traversata e' tempo di riposo."""
        return self._ore_guida[(a, b)]

    def traghetto(self, a: int, b: int) -> dict | None:
        """Collegamento marittimo della tratta, se presente."""
        return self._traghetti.get((a, b))

    def costo_traghetti(self, sequenza: list[int]) -> float:
        """Costo dei traghetti lungo un percorso."""
        return sum(
            (self.traghetto(x, y) or {}).get("costo_eur", 0.0)
            for x, y in zip(sequenza, sequenza[1:])
        )

    def km_percorso(self, sequenza: list[int]) -> float:
        return sum(self.km(x, y) for x, y in zip(sequenza, sequenza[1:]))

    def ore_percorso(self, sequenza: list[int]) -> float:
        return sum(self.ore(x, y) for x, y in zip(sequenza, sequenza[1:]))
