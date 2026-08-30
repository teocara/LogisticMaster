"""Esecuzione dei viaggi e misura del servizio a consuntivo.

Il piano di trasporto e' una previsione; qui inizia la vita reale del
trasporto. Ogni giro pianificato diventa un **viaggio** assegnabile a un
mezzo o a un vettore, che avanza tappa per tappa fino alla chiusura.

Dagli esiti registrati sulle tappe si ricava l'**OTIF a consuntivo**:

* **On Time** - la merce e' arrivata entro la finestra di consegna
  concordata (data richiesta dall'ordine e orario di chiusura del sito
  destinatario), con una tolleranza configurabile;
* **In Full** - tutte le righe dell'ordine sono state consegnate per
  intero, entro l'eventuale tolleranza percentuale;
* **OTIF** - l'ordine soddisfa entrambe le condizioni.

Un ordine consegnato in ritardo *e* incompleto pesa una sola volta
sull'OTIF, ma compare in entrambi gli indicatori parziali: e' la lettura
che permette di capire se il problema e' di trasporto o di magazzino.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .. import db

# Stati ammessi e transizioni consentite del viaggio.
TRANSIZIONI: dict[str, set[str]] = {
    "PIANIFICATO": {"ASSEGNATO", "ANNULLATO"},
    "ASSEGNATO": {"IN_CORSO", "PIANIFICATO", "ANNULLATO"},
    "IN_CORSO": {"COMPLETATO", "ANNULLATO"},
    "COMPLETATO": set(),
    "ANNULLATO": set(),
}

# Causali di mancato servizio, per l'analisi di Pareto delle cause.
CAUSALI = {
    "TRAFFICO": "Traffico o viabilità",
    "GUASTO": "Guasto o fermo mezzo",
    "MERCE_MANCANTE": "Merce non disponibile alla partenza",
    "ATTESA_SCARICO": "Attesa allo scarico presso il destinatario",
    "SITO_CHIUSO": "Destinatario chiuso o non ricevente",
    "DOCUMENTI": "Documenti di trasporto incompleti",
    "METEO": "Condizioni meteo",
    "ALTRO": "Altra causa",
}

CAUSALE_PIANO = "PIANIFICAZIONE"
DESCRIZIONE_CAUSALE_PIANO = "Consegna già pianificata oltre la finestra richiesta"
"""Non e' un disservizio dell'esecuzione: e' il piano ad avere accettato il ritardo
(tipicamente una lunga percorrenza servita in piu' giorni). Va letta a parte,
perche' si corregge pianificando diversamente, non spingendo sugli autisti."""

TOLLERANZA_RITARDO_MINUTI = 30.0
"""Franchigia sull'orario di chiusura prima di considerare la consegna in ritardo."""

TOLLERANZA_QUANTITA_PCT = 0.0
"""Scostamento accettato sulla quantita' consegnata (0 = consegna completa)."""


class ErroreEsecuzione(Exception):
    """Operazione non ammessa dallo stato corrente del viaggio."""


def _adesso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def formato_ora(ora: float) -> str:
    """Ora decimale in formato HH:MM, come la legge chi lavora in piazzale."""
    ore = int(ora)
    minuti = int(round((ora - ore) * 60))
    if minuti == 60:
        ore, minuti = ore + 1, 0
    return f"{ore:02d}:{minuti:02d}"


def _somma_giorni(data_iso: str, giorni: int) -> str:
    return (date.fromisoformat(data_iso) + timedelta(days=giorni)).isoformat()


def _registra_evento(conn, viaggio_id: int, tipo: str, descrizione: str, tappa_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO viaggi_eventi (viaggio_id,tappa_id,momento,tipo,descrizione) VALUES (?,?,?,?,?)",
        (viaggio_id, tappa_id, _adesso(), tipo, descrizione),
    )


# --------------------------------------------------------------------------
# Dal piano ai viaggi
# --------------------------------------------------------------------------


def crea_viaggi_da_piano(piano_id: int, risultato: dict) -> list[int]:
    """Trasforma i giri di un piano in viaggi eseguibili.

    Ogni fermata diventa una tappa con orario previsto e righe da
    consegnare; gli ordini coinvolti passano in stato PIANIFICATO.
    """
    creati: list[int] = []
    with db.transazione() as conn:
        for giro in risultato.get("giri", []):
            cur = conn.execute(
                """INSERT INTO viaggi (piano_id,giro_id,data,origine_id,profilo,stato,esecuzione,
                       km_previsti,ore_previste,giorni_previsti,costo_previsto,partenza_prevista)
                   VALUES (?,?,?,?,?,'PIANIFICATO',?,?,?,?,?,?)""",
                (
                    piano_id,
                    giro["id"],
                    giro["data"],
                    giro["deposito_id"],
                    giro["veicolo"],
                    giro.get("scelta_consigliata", "PROPRIO"),
                    giro["km"],
                    giro["durata_ore"],
                    giro.get("giorni_impegno", 1),
                    giro["costo"]["totale"],
                    risultato.get("parametri", {}).get("ora_partenza", 6.0),
                ),
            )
            viaggio_id = cur.lastrowid
            creati.append(viaggio_id)

            # Il cronoprogramma contiene anche il rientro al deposito:
            # le tappe sono tante quante le fermate del giro.
            for indice, fermata in enumerate(giro["fermate"]):
                tappa = giro["cronoprogramma"][indice]
                cur = conn.execute(
                    """INSERT INTO viaggi_tappe (viaggio_id,sequenza,sito_id,data_prevista,ora_prevista)
                       VALUES (?,?,?,?,?)""",
                    (
                        viaggio_id,
                        indice + 1,
                        fermata["sito_id"],
                        _somma_giorni(giro["data"], int(tappa.get("giorno", 1)) - 1),
                        tappa["arrivo"],
                    ),
                )
                tappa_id = cur.lastrowid
                for riferimento in fermata["spedizioni"]:
                    ordine = conn.execute(
                        "SELECT id FROM ordini WHERE riferimento = ?", (riferimento,)
                    ).fetchone()
                    if not ordine:
                        continue
                    for riga in conn.execute(
                        "SELECT articolo_id, quantita FROM ordini_righe WHERE ordine_id = ?",
                        (ordine["id"],),
                    ).fetchall():
                        conn.execute(
                            """INSERT INTO tappe_righe (tappa_id,ordine_id,articolo_id,quantita_richiesta)
                               VALUES (?,?,?,?)""",
                            (tappa_id, ordine["id"], riga["articolo_id"], riga["quantita"]),
                        )
                    conn.execute(
                        "UPDATE ordini SET stato='PIANIFICATO' WHERE id = ?", (ordine["id"],)
                    )
            _registra_evento(conn, viaggio_id, "CREAZIONE", f"Viaggio generato dal piano {piano_id}")
    return creati


# --------------------------------------------------------------------------
# Avanzamento del viaggio
# --------------------------------------------------------------------------


def _viaggio(conn, viaggio_id: int) -> dict:
    riga = conn.execute("SELECT * FROM viaggi WHERE id = ?", (viaggio_id,)).fetchone()
    if not riga:
        raise ErroreEsecuzione(f"Viaggio inesistente: {viaggio_id}")
    return dict(riga)


def _verifica_transizione(stato_attuale: str, nuovo_stato: str) -> None:
    if nuovo_stato not in TRANSIZIONI[stato_attuale]:
        ammessi = ", ".join(sorted(TRANSIZIONI[stato_attuale])) or "nessuno"
        raise ErroreEsecuzione(
            f"Da '{stato_attuale}' non si può passare a '{nuovo_stato}'. Stati ammessi: {ammessi}"
        )


def assegna(
    viaggio_id: int,
    veicolo_id: int | None = None,
    vettore_id: int | None = None,
    autista: str | None = None,
) -> dict:
    """Assegna il viaggio a un mezzo aziendale oppure a un vettore terzo."""
    if bool(veicolo_id) == bool(vettore_id):
        raise ErroreEsecuzione("Indicare il mezzo aziendale oppure il vettore, non entrambi")

    with db.transazione() as conn:
        viaggio = _viaggio(conn, viaggio_id)
        _verifica_transizione(viaggio["stato"], "ASSEGNATO")

        if veicolo_id:
            veicolo = conn.execute("SELECT * FROM veicoli WHERE id = ?", (veicolo_id,)).fetchone()
            if not veicolo:
                raise ErroreEsecuzione(f"Veicolo inesistente: {veicolo_id}")
            occupato = conn.execute(
                """SELECT giro_id FROM viaggi
                   WHERE veicolo_id = ? AND data = ? AND stato IN ('ASSEGNATO','IN_CORSO') AND id <> ?""",
                (veicolo_id, viaggio["data"], viaggio_id),
            ).fetchone()
            if occupato:
                raise ErroreEsecuzione(
                    f"Il mezzo {veicolo['targa']} è già impegnato il {viaggio['data']} sul viaggio {occupato['giro_id']}"
                )
            descrizione = f"Assegnato al mezzo {veicolo['targa']}"
            if autista:
                descrizione += f", autista {autista}"
        else:
            vettore = conn.execute("SELECT * FROM vettori WHERE id = ?", (vettore_id,)).fetchone()
            if not vettore:
                raise ErroreEsecuzione(f"Vettore inesistente: {vettore_id}")
            descrizione = f"Affidato al vettore {vettore['nome']}"

        conn.execute(
            """UPDATE viaggi SET stato='ASSEGNATO', veicolo_id=?, vettore_id=?, autista=?,
                   esecuzione=? WHERE id = ?""",
            (veicolo_id, vettore_id, autista, "PROPRIO" if veicolo_id else "TERZI", viaggio_id),
        )
        _registra_evento(conn, viaggio_id, "ASSEGNAZIONE", descrizione)
    return dettaglio_viaggio(viaggio_id)


def registra_partenza(viaggio_id: int, momento: str | None = None) -> dict:
    """Mette il viaggio in corso registrandone la partenza effettiva."""
    with db.transazione() as conn:
        viaggio = _viaggio(conn, viaggio_id)
        _verifica_transizione(viaggio["stato"], "IN_CORSO")
        partenza = momento or _adesso()
        conn.execute(
            "UPDATE viaggi SET stato='IN_CORSO', partenza_effettiva=? WHERE id = ?",
            (partenza, viaggio_id),
        )
        _registra_evento(conn, viaggio_id, "PARTENZA", f"Partenza registrata alle {partenza}")
    return dettaglio_viaggio(viaggio_id)


def registra_esito_tappa(
    tappa_id: int,
    data_effettiva: str,
    ora_effettiva: float,
    quantita: dict[int, float] | None = None,
    causale: str | None = None,
    note: str | None = None,
    non_eseguita: bool = False,
) -> dict:
    """Registra l'esito di una tappa: orario di arrivo e quantita' scaricate.

    ``quantita`` mappa l'identificativo di riga della tappa sulla quantita'
    effettivamente consegnata. Le righe non indicate si considerano
    consegnate per intero, tranne quando la tappa non e' stata eseguita.
    """
    if causale and causale not in CAUSALI:
        raise ErroreEsecuzione(f"Causale sconosciuta: {causale}. Ammesse: {', '.join(CAUSALI)}")

    with db.transazione() as conn:
        tappa = conn.execute("SELECT * FROM viaggi_tappe WHERE id = ?", (tappa_id,)).fetchone()
        if not tappa:
            raise ErroreEsecuzione(f"Tappa inesistente: {tappa_id}")
        viaggio = _viaggio(conn, tappa["viaggio_id"])
        if viaggio["stato"] != "IN_CORSO":
            raise ErroreEsecuzione(
                f"Il viaggio {viaggio['giro_id']} è in stato '{viaggio['stato']}': "
                "registrare prima la partenza"
            )

        righe = [dict(r) for r in conn.execute(
            "SELECT * FROM tappe_righe WHERE tappa_id = ?", (tappa_id,)
        ).fetchall()]
        quantita = quantita or {}
        sconosciute = set(quantita) - {r["id"] for r in righe}
        if sconosciute:
            raise ErroreEsecuzione(
                f"Righe non appartenenti alla tappa: {', '.join(str(x) for x in sorted(sconosciute))}"
            )

        consegnato_tutto = True
        consegnato_nulla = True
        for riga in righe:
            if non_eseguita:
                consegnata = 0.0
            else:
                consegnata = float(quantita.get(riga["id"], riga["quantita_richiesta"]))
            if consegnata < 0 or consegnata > riga["quantita_richiesta"] + 1e-9:
                raise ErroreEsecuzione(
                    f"Quantità consegnata non valida per la riga {riga['id']}: "
                    f"ammesso da 0 a {riga['quantita_richiesta']}"
                )
            conn.execute(
                "UPDATE tappe_righe SET quantita_consegnata = ? WHERE id = ?", (consegnata, riga["id"])
            )
            if consegnata < riga["quantita_richiesta"] - 1e-9:
                consegnato_tutto = False
            if consegnata > 1e-9:
                consegnato_nulla = False

        if non_eseguita or (consegnato_nulla and righe):
            stato = "NON_ESEGUITA" if non_eseguita else "RIFIUTATA"
        elif consegnato_tutto:
            stato = "CONSEGNATA"
        else:
            stato = "PARZIALE"

        conn.execute(
            """UPDATE viaggi_tappe SET data_effettiva=?, ora_effettiva=?, stato=?, causale=?, note=?
               WHERE id = ?""",
            (data_effettiva, ora_effettiva, stato, causale, note, tappa_id),
        )
        _registra_evento(
            conn,
            viaggio["id"],
            "ESITO_TAPPA",
            f"Tappa {tappa['sequenza']}: {stato.lower()} il {data_effettiva} alle {formato_ora(ora_effettiva)}"
            + (f" ({CAUSALI[causale]})" if causale else ""),
            tappa_id,
        )

        # Gli ordini interamente serviti passano a CONSEGNATO.
        for ordine_id in {r["ordine_id"] for r in righe}:
            residuo = conn.execute(
                """SELECT SUM(quantita_richiesta - COALESCE(quantita_consegnata, quantita_richiesta)) AS mancante,
                          SUM(CASE WHEN quantita_consegnata IS NULL THEN 1 ELSE 0 END) AS aperte
                   FROM tappe_righe WHERE ordine_id = ?""",
                (ordine_id,),
            ).fetchone()
            if residuo["aperte"] == 0:
                nuovo = "CONSEGNATO" if (residuo["mancante"] or 0) <= 1e-9 else "IN_TRANSITO"
                conn.execute("UPDATE ordini SET stato=? WHERE id = ?", (nuovo, ordine_id))
    return dettaglio_tappa(tappa_id)


def chiudi_viaggio(
    viaggio_id: int,
    km_effettivi: float | None = None,
    costo_effettivo: float | None = None,
    rientro: str | None = None,
) -> dict:
    """Chiude il viaggio con i dati a consuntivo di percorrenza e costo."""
    with db.transazione() as conn:
        viaggio = _viaggio(conn, viaggio_id)
        _verifica_transizione(viaggio["stato"], "COMPLETATO")
        aperte = conn.execute(
            "SELECT COUNT(*) AS n FROM viaggi_tappe WHERE viaggio_id = ? AND stato = 'DA_ESEGUIRE'",
            (viaggio_id,),
        ).fetchone()["n"]
        if aperte:
            raise ErroreEsecuzione(
                f"Restano {aperte} tappe senza esito: registrarle prima di chiudere il viaggio"
            )
        conn.execute(
            """UPDATE viaggi SET stato='COMPLETATO', km_effettivi=?, costo_effettivo=?, rientro_effettivo=?
               WHERE id = ?""",
            (
                km_effettivi if km_effettivi is not None else viaggio["km_previsti"],
                costo_effettivo if costo_effettivo is not None else viaggio["costo_previsto"],
                rientro or _adesso(),
                viaggio_id,
            ),
        )
        _registra_evento(conn, viaggio_id, "CHIUSURA", "Viaggio chiuso a consuntivo")
    return dettaglio_viaggio(viaggio_id)


def annulla_viaggio(viaggio_id: int, motivo: str) -> dict:
    """Annulla un viaggio non ancora concluso, riaprendo i suoi ordini."""
    with db.transazione() as conn:
        viaggio = _viaggio(conn, viaggio_id)
        _verifica_transizione(viaggio["stato"], "ANNULLATO")
        conn.execute("UPDATE viaggi SET stato='ANNULLATO', note=? WHERE id = ?", (motivo, viaggio_id))
        conn.execute(
            """UPDATE ordini SET stato='DA_PIANIFICARE' WHERE id IN (
                   SELECT DISTINCT r.ordine_id FROM tappe_righe r
                   JOIN viaggi_tappe t ON t.id = r.tappa_id WHERE t.viaggio_id = ?)""",
            (viaggio_id,),
        )
        _registra_evento(conn, viaggio_id, "ANNULLAMENTO", motivo)
    return dettaglio_viaggio(viaggio_id)


# --------------------------------------------------------------------------
# Lettura
# --------------------------------------------------------------------------

_SELECT_VIAGGIO = """
    SELECT v.*, s.codice AS origine_codice, s.nome AS origine_nome,
           ve.targa AS veicolo_targa, vt.nome AS vettore_nome
    FROM viaggi v
    JOIN siti s ON s.id = v.origine_id
    LEFT JOIN veicoli ve ON ve.id = v.veicolo_id
    LEFT JOIN vettori vt ON vt.id = v.vettore_id
"""


def elenco_viaggi(
    stato: str | None = None,
    data_da: str | None = None,
    data_a: str | None = None,
    limite: int = 200,
    piano_id: int | None = None,
) -> list[dict]:
    """Viaggi con avanzamento delle tappe e scostamento sul costo."""
    condizioni, parametri = [], []
    if piano_id:
        condizioni.append("v.piano_id = ?")
        parametri.append(piano_id)
    if stato:
        condizioni.append("v.stato = ?")
        parametri.append(stato)
    if data_da:
        condizioni.append("v.data >= ?")
        parametri.append(data_da)
    if data_a:
        condizioni.append("v.data <= ?")
        parametri.append(data_a)
    dove = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    viaggi = db.query(
        f"{_SELECT_VIAGGIO} {dove} ORDER BY v.data, v.giro_id LIMIT ?", (*parametri, limite)
    )
    if not viaggi:
        return []

    identificativi = ",".join(str(v["id"]) for v in viaggi)
    avanzamento = {
        r["viaggio_id"]: r
        for r in db.query(
            f"""SELECT viaggio_id, COUNT(*) AS tappe,
                       SUM(CASE WHEN stato <> 'DA_ESEGUIRE' THEN 1 ELSE 0 END) AS eseguite
                FROM viaggi_tappe WHERE viaggio_id IN ({identificativi}) GROUP BY viaggio_id"""
        )
    }
    for v in viaggi:
        progresso = avanzamento.get(v["id"], {"tappe": 0, "eseguite": 0})
        v["tappe"] = progresso["tappe"]
        v["tappe_eseguite"] = progresso["eseguite"]
        v["avanzamento_pct"] = round(
            (progresso["eseguite"] / progresso["tappe"] * 100) if progresso["tappe"] else 0.0, 1
        )
        v["scostamento_costo"] = (
            round(v["costo_effettivo"] - v["costo_previsto"], 2)
            if v["costo_effettivo"] is not None
            else None
        )
        v["scostamento_km"] = (
            round(v["km_effettivi"] - v["km_previsti"], 1) if v["km_effettivi"] is not None else None
        )
    return viaggi


def dettaglio_viaggio(viaggio_id: int) -> dict:
    """Viaggio con tappe, righe e diario degli eventi."""
    viaggio = db.query_uno(f"{_SELECT_VIAGGIO} WHERE v.id = ?", (viaggio_id,))
    if not viaggio:
        raise ErroreEsecuzione(f"Viaggio inesistente: {viaggio_id}")
    viaggio["tappe"] = [
        dettaglio_tappa(t["id"])
        for t in db.query(
            "SELECT id FROM viaggi_tappe WHERE viaggio_id = ? ORDER BY sequenza", (viaggio_id,)
        )
    ]
    viaggio["eventi"] = db.query(
        "SELECT momento, tipo, descrizione FROM viaggi_eventi WHERE viaggio_id = ? ORDER BY id",
        (viaggio_id,),
    )
    viaggio["scostamento_costo"] = (
        round(viaggio["costo_effettivo"] - viaggio["costo_previsto"], 2)
        if viaggio["costo_effettivo"] is not None
        else None
    )
    viaggio["scostamento_km"] = (
        round(viaggio["km_effettivi"] - viaggio["km_previsti"], 1)
        if viaggio["km_effettivi"] is not None
        else None
    )
    return viaggio


def dettaglio_tappa(tappa_id: int) -> dict:
    tappa = db.query_uno(
        """SELECT t.*, s.codice AS sito_codice, s.nome AS sito_nome, s.comune, s.provincia,
                  s.apertura, s.chiusura
           FROM viaggi_tappe t JOIN siti s ON s.id = t.sito_id WHERE t.id = ?""",
        (tappa_id,),
    )
    if not tappa:
        raise ErroreEsecuzione(f"Tappa inesistente: {tappa_id}")
    tappa["righe"] = db.query(
        """SELECT r.*, o.riferimento, a.codice AS articolo_codice, a.descrizione AS articolo_descrizione
           FROM tappe_righe r
           JOIN ordini o ON o.id = r.ordine_id
           JOIN articoli a ON a.id = r.articolo_id
           WHERE r.tappa_id = ? ORDER BY o.riferimento, a.codice""",
        (tappa_id,),
    )
    tappa["ritardo_minuti"] = _ritardo_minuti(tappa)
    return tappa


def _ritardo_minuti(tappa: dict) -> float | None:
    """Minuti di ritardo rispetto all'orario previsto dal piano."""
    if not tappa.get("data_effettiva"):
        return None
    giorni = (
        date.fromisoformat(tappa["data_effettiva"]) - date.fromisoformat(tappa["data_prevista"])
    ).days
    return round((giorni * 24 + tappa["ora_effettiva"] - tappa["ora_prevista"]) * 60, 1)
