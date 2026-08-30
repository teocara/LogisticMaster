"""Pianificazione delle scorte e bilanciamento fra i siti della rete.

Il modulo copre tre passaggi tipici della pianificazione multi-plant:

1. calcolo dei parametri di scorta per coppia sito/articolo
   (scorta di sicurezza, punto di riordino, lotto economico);
2. individuazione dei fabbisogni netti e delle eccedenze;
3. proposta dei trasferimenti inter-sito che coprono i fabbisogni al
   minimo costo di trasporto, prima di ricorrere a un riordino esterno.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geo import MatriceDistanze

# Coefficiente di sicurezza z per livello di servizio atteso.
# Valori della normale standard inversa per i livelli piu' usati.
Z_LIVELLO_SERVIZIO: dict[float, float] = {
    0.50: 0.00,
    0.80: 0.84,
    0.85: 1.04,
    0.90: 1.28,
    0.95: 1.65,
    0.97: 1.88,
    0.98: 2.05,
    0.99: 2.33,
    0.995: 2.58,
}


def z_score(livello_servizio: float) -> float:
    """Coefficiente z per il livello di servizio richiesto (interpolato)."""
    livelli = sorted(Z_LIVELLO_SERVIZIO)
    if livello_servizio <= livelli[0]:
        return Z_LIVELLO_SERVIZIO[livelli[0]]
    if livello_servizio >= livelli[-1]:
        return Z_LIVELLO_SERVIZIO[livelli[-1]]
    for basso, alto in zip(livelli, livelli[1:]):
        if basso <= livello_servizio <= alto:
            peso = (livello_servizio - basso) / (alto - basso)
            return Z_LIVELLO_SERVIZIO[basso] + peso * (
                Z_LIVELLO_SERVIZIO[alto] - Z_LIVELLO_SERVIZIO[basso]
            )
    return Z_LIVELLO_SERVIZIO[livelli[-1]]


@dataclass
class ParametriScorta:
    """Parametri di riordino calcolati per una coppia sito/articolo."""

    sito_id: int
    articolo_id: int
    domanda_media_giorno: float
    deviazione_domanda: float
    lead_time_giorni: float
    livello_servizio: float
    scorta_sicurezza: float
    punto_riordino: float
    lotto_economico: float
    copertura_giorni: float

    def as_dict(self) -> dict:
        return {
            "sito_id": self.sito_id,
            "articolo_id": self.articolo_id,
            "domanda_media_giorno": round(self.domanda_media_giorno, 2),
            "deviazione_domanda": round(self.deviazione_domanda, 2),
            "lead_time_giorni": self.lead_time_giorni,
            "livello_servizio": self.livello_servizio,
            "scorta_sicurezza": round(self.scorta_sicurezza, 1),
            "punto_riordino": round(self.punto_riordino, 1),
            "lotto_economico": round(self.lotto_economico, 1),
            "copertura_giorni": round(self.copertura_giorni, 1),
        }


def scorta_sicurezza(
    domanda_media_giorno: float,
    deviazione_domanda_giorno: float,
    lead_time_giorni: float,
    deviazione_lead_time_giorni: float,
    livello_servizio: float,
) -> float:
    """Scorta di sicurezza con variabilita' sia di domanda sia di lead time.

    SS = z * sqrt(LT * sigma_domanda^2 + domanda_media^2 * sigma_LT^2)
    """
    varianza = (
        lead_time_giorni * deviazione_domanda_giorno**2
        + (domanda_media_giorno**2) * (deviazione_lead_time_giorni**2)
    )
    return max(z_score(livello_servizio) * math.sqrt(max(varianza, 0.0)), 0.0)


def lotto_economico(
    domanda_annua: float, costo_ordine: float, costo_mantenimento_unitario: float
) -> float:
    """Lotto economico di riordino (formula di Wilson)."""
    if domanda_annua <= 0 or costo_mantenimento_unitario <= 0:
        return 0.0
    return math.sqrt(2 * domanda_annua * costo_ordine / costo_mantenimento_unitario)


def calcola_parametri(
    sito_id: int,
    articolo_id: int,
    domanda_media_giorno: float,
    deviazione_domanda_giorno: float,
    lead_time_giorni: float,
    deviazione_lead_time_giorni: float,
    livello_servizio: float,
    giacenza: float,
    costo_ordine: float = 85.0,
    valore_unitario: float = 10.0,
    tasso_mantenimento: float = 0.22,
) -> ParametriScorta:
    """Calcola i parametri di riordino per una coppia sito/articolo."""
    ss = scorta_sicurezza(
        domanda_media_giorno,
        deviazione_domanda_giorno,
        lead_time_giorni,
        deviazione_lead_time_giorni,
        livello_servizio,
    )
    rop = domanda_media_giorno * lead_time_giorni + ss
    eoq = lotto_economico(
        domanda_media_giorno * 250,
        costo_ordine,
        max(valore_unitario * tasso_mantenimento, 0.01),
    )
    copertura = giacenza / domanda_media_giorno if domanda_media_giorno > 0 else 999.0
    return ParametriScorta(
        sito_id=sito_id,
        articolo_id=articolo_id,
        domanda_media_giorno=domanda_media_giorno,
        deviazione_domanda=deviazione_domanda_giorno,
        lead_time_giorni=lead_time_giorni,
        livello_servizio=livello_servizio,
        scorta_sicurezza=ss,
        punto_riordino=rop,
        lotto_economico=eoq,
        copertura_giorni=copertura,
    )


# --------------------------------------------------------------------------
# Bilanciamento della rete
# --------------------------------------------------------------------------


@dataclass
class Squilibrio:
    """Fabbisogno (negativo) o eccedenza (positiva) di un sito."""

    sito_id: int
    articolo_id: int
    giacenza: float
    punto_riordino: float
    scorta_massima: float

    @property
    def fabbisogno(self) -> float:
        """Quantita' mancante per riportare la giacenza al punto di riordino."""
        return max(self.punto_riordino - self.giacenza, 0.0)

    @property
    def eccedenza(self) -> float:
        """Quantita' cedibile senza scendere sotto il punto di riordino."""
        return max(self.giacenza - max(self.punto_riordino, 0.0), 0.0)


@dataclass
class PropostaTrasferimento:
    """Trasferimento inter-sito proposto dal pianificatore."""

    articolo_id: int
    origine_id: int
    destino_id: int
    quantita: float
    km: float
    urgenza: str
    motivo: str
    copertura_residua_origine: float = 0.0

    def as_dict(self) -> dict:
        return {
            "articolo_id": self.articolo_id,
            "origine_id": self.origine_id,
            "destino_id": self.destino_id,
            "quantita": round(self.quantita, 1),
            "km": round(self.km, 1),
            "urgenza": self.urgenza,
            "motivo": self.motivo,
            "copertura_residua_origine": round(self.copertura_residua_origine, 1),
        }


def _urgenza(copertura_giorni: float, lead_time: float) -> str:
    """Classifica l'urgenza confrontando copertura residua e lead time."""
    if copertura_giorni <= 0:
        return "ROTTURA"
    if copertura_giorni < lead_time:
        return "CRITICA"
    if copertura_giorni < lead_time * 2:
        return "ALTA"
    return "NORMALE"


def piano_bilanciamento(
    squilibri: list[Squilibrio],
    matrice: MatriceDistanze,
    coperture: dict[tuple[int, int], float] | None = None,
    lead_time_giorni: float = 3.0,
    quantita_minima: float = 1.0,
    km_massimi: float = 900.0,
) -> list[PropostaTrasferimento]:
    """Copre i fabbisogni con le eccedenze della rete al minimo percorso.

    Strategia greedy per articolo: i fabbisogni sono serviti in ordine di
    urgenza e ciascuno attinge dalle eccedenze piu' vicine. E' la logica
    che un pianificatore applica manualmente, resa ripetibile e completa.
    """
    coperture = coperture or {}
    proposte: list[PropostaTrasferimento] = []

    per_articolo: dict[int, list[Squilibrio]] = {}
    for s in squilibri:
        per_articolo.setdefault(s.articolo_id, []).append(s)

    for articolo_id, righe in per_articolo.items():
        disponibile = {
            r.sito_id: r.eccedenza for r in righe if r.eccedenza >= quantita_minima
        }
        richieste = [r for r in righe if r.fabbisogno >= quantita_minima]
        richieste.sort(
            key=lambda r: coperture.get((r.sito_id, articolo_id), 999.0)
        )

        for richiesta in richieste:
            residuo = richiesta.fabbisogno
            copertura = coperture.get((richiesta.sito_id, articolo_id), 0.0)
            urgenza = _urgenza(copertura, lead_time_giorni)

            fonti = sorted(
                (sid for sid, qta in disponibile.items() if qta >= quantita_minima and sid != richiesta.sito_id),
                key=lambda sid: matrice.km(sid, richiesta.sito_id),
            )
            for origine in fonti:
                if residuo < quantita_minima:
                    break
                km = matrice.km(origine, richiesta.sito_id)
                if km > km_massimi:
                    continue
                quantita = min(residuo, disponibile[origine])
                # Non si supera la scorta massima del sito ricevente.
                spazio = richiesta.scorta_massima - richiesta.giacenza
                if spazio > 0:
                    quantita = min(quantita, spazio)
                if quantita < quantita_minima:
                    continue
                disponibile[origine] -= quantita
                residuo -= quantita
                proposte.append(
                    PropostaTrasferimento(
                        articolo_id=articolo_id,
                        origine_id=origine,
                        destino_id=richiesta.sito_id,
                        quantita=quantita,
                        km=km,
                        urgenza=urgenza,
                        motivo="Copertura fabbisogno da eccedenza di rete",
                        copertura_residua_origine=copertura,
                    )
                )

            if residuo >= quantita_minima:
                proposte.append(
                    PropostaTrasferimento(
                        articolo_id=articolo_id,
                        origine_id=0,  # 0 = riordino esterno / produzione
                        destino_id=richiesta.sito_id,
                        quantita=residuo,
                        km=0.0,
                        urgenza=urgenza,
                        motivo="Rete senza eccedenze: richiesta a produzione o fornitore",
                        copertura_residua_origine=copertura,
                    )
                )

    proposte.sort(key=lambda p: (["ROTTURA", "CRITICA", "ALTA", "NORMALE"].index(p.urgenza), -p.quantita))
    return proposte
