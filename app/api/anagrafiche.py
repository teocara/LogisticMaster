"""API delle anagrafiche: siti, articoli, giacenze, veicoli, vettori, ordini."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..core.costi import PROFILI_VEICOLO
from ..models import ArticoloInput, GiacenzaInput, OrdineInput, SitoInput

router = APIRouter(prefix="/api", tags=["anagrafiche"])


# --------------------------------------------------------------------- siti
@router.get("/siti")
def elenco_siti(tipo: str | None = None, solo_attivi: bool = True) -> list[dict]:
    condizioni, parametri = [], []
    if tipo:
        condizioni.append("tipo = ?")
        parametri.append(tipo)
    if solo_attivi:
        condizioni.append("attivo = 1")
    dove = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    return db.query(f"SELECT * FROM siti {dove} ORDER BY tipo, nome", tuple(parametri))


@router.get("/siti/{sito_id}")
def dettaglio_sito(sito_id: int) -> dict:
    sito = db.query_uno("SELECT * FROM siti WHERE id = ?", (sito_id,))
    if not sito:
        raise HTTPException(404, "Sito non trovato")
    sito["giacenze"] = db.query(
        """SELECT g.*, a.codice AS articolo_codice, a.descrizione AS articolo_descrizione
           FROM giacenze g JOIN articoli a ON a.id = g.articolo_id
           WHERE g.sito_id = ? ORDER BY a.codice""",
        (sito_id,),
    )
    sito["veicoli"] = db.query("SELECT * FROM veicoli WHERE sito_base = ?", (sito_id,))
    return sito


@router.post("/siti", status_code=201)
def crea_sito(dati: SitoInput) -> dict:
    if db.query_uno("SELECT id FROM siti WHERE codice = ?", (dati.codice,)):
        raise HTTPException(409, f"Codice sito gia' presente: {dati.codice}")
    campi = dati.model_dump()
    campi["attivo"] = int(campi["attivo"])
    colonne = ",".join(campi)
    segnaposto = ",".join("?" * len(campi))
    nuovo_id = db.esegui(
        f"INSERT INTO siti ({colonne}) VALUES ({segnaposto})", tuple(campi.values())
    )
    return db.query_uno("SELECT * FROM siti WHERE id = ?", (nuovo_id,))


@router.put("/siti/{sito_id}")
def aggiorna_sito(sito_id: int, dati: SitoInput) -> dict:
    if not db.query_uno("SELECT id FROM siti WHERE id = ?", (sito_id,)):
        raise HTTPException(404, "Sito non trovato")
    campi = dati.model_dump()
    campi["attivo"] = int(campi["attivo"])
    assegnazioni = ",".join(f"{c} = ?" for c in campi)
    db.esegui(f"UPDATE siti SET {assegnazioni} WHERE id = ?", (*campi.values(), sito_id))
    return db.query_uno("SELECT * FROM siti WHERE id = ?", (sito_id,))


@router.delete("/siti/{sito_id}")
def disattiva_sito(sito_id: int) -> dict:
    """Disattivazione logica: i siti restano referenziati dallo storico."""
    if not db.query_uno("SELECT id FROM siti WHERE id = ?", (sito_id,)):
        raise HTTPException(404, "Sito non trovato")
    db.esegui("UPDATE siti SET attivo = 0 WHERE id = ?", (sito_id,))
    return {"esito": "disattivato", "sito_id": sito_id}


# ----------------------------------------------------------------- articoli
@router.get("/articoli")
def elenco_articoli(famiglia: str | None = None) -> list[dict]:
    if famiglia:
        return db.query("SELECT * FROM articoli WHERE famiglia = ? ORDER BY codice", (famiglia,))
    return db.query("SELECT * FROM articoli ORDER BY codice")


@router.post("/articoli", status_code=201)
def crea_articolo(dati: ArticoloInput) -> dict:
    if db.query_uno("SELECT id FROM articoli WHERE codice = ?", (dati.codice,)):
        raise HTTPException(409, f"Codice articolo gia' presente: {dati.codice}")
    campi = dati.model_dump()
    for booleano in ("adr", "sovrapponibile", "temperatura_controllata"):
        campi[booleano] = int(campi[booleano])
    colonne = ",".join(campi)
    nuovo_id = db.esegui(
        f"INSERT INTO articoli ({colonne}) VALUES ({','.join('?' * len(campi))})",
        tuple(campi.values()),
    )
    return db.query_uno("SELECT * FROM articoli WHERE id = ?", (nuovo_id,))


# ----------------------------------------------------------------- giacenze
@router.get("/giacenze")
def elenco_giacenze(sito_id: int | None = None, articolo_id: int | None = None) -> list[dict]:
    condizioni, parametri = [], []
    if sito_id:
        condizioni.append("g.sito_id = ?")
        parametri.append(sito_id)
    if articolo_id:
        condizioni.append("g.articolo_id = ?")
        parametri.append(articolo_id)
    dove = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    return db.query(
        f"""SELECT g.*, s.codice AS sito_codice, s.nome AS sito_nome,
                   a.codice AS articolo_codice, a.descrizione AS articolo_descrizione,
                   a.classe_abc, a.valore_unitario
            FROM giacenze g
            JOIN siti s ON s.id = g.sito_id
            JOIN articoli a ON a.id = g.articolo_id
            {dove}
            ORDER BY s.codice, a.codice""",
        tuple(parametri),
    )


@router.put("/giacenze")
def aggiorna_giacenza(dati: GiacenzaInput) -> dict:
    campi = dati.model_dump()
    colonne = ",".join(campi)
    aggiornamenti = ",".join(
        f"{c} = excluded.{c}" for c in campi if c not in ("sito_id", "articolo_id")
    )
    db.esegui(
        f"""INSERT INTO giacenze ({colonne}) VALUES ({','.join('?' * len(campi))})
            ON CONFLICT (sito_id, articolo_id) DO UPDATE SET {aggiornamenti}""",
        tuple(campi.values()),
    )
    return db.query_uno(
        "SELECT * FROM giacenze WHERE sito_id = ? AND articolo_id = ?",
        (dati.sito_id, dati.articolo_id),
    )


# ------------------------------------------------------------------ flotta
@router.get("/veicoli")
def elenco_veicoli() -> list[dict]:
    veicoli = db.query(
        """SELECT v.*, s.codice AS base_codice, s.nome AS base_nome
           FROM veicoli v JOIN siti s ON s.id = v.sito_base ORDER BY v.targa"""
    )
    for v in veicoli:
        profilo = PROFILI_VEICOLO.get(v["profilo"])
        if profilo:
            v["descrizione_profilo"] = profilo.descrizione
            v["portata_kg"] = profilo.portata_kg
            v["volume_m3"] = profilo.volume_m3
            v["posti_pallet"] = profilo.posti_pallet
            v["costo_variabile_km"] = profilo.costo_variabile_km
            v["costo_autista_ora"] = profilo.costo_autista_ora
    return veicoli


@router.get("/profili-veicolo")
def elenco_profili() -> list[dict]:
    return [
        {
            "codice": p.codice,
            "descrizione": p.descrizione,
            "portata_kg": p.portata_kg,
            "volume_m3": p.volume_m3,
            "posti_pallet": p.posti_pallet,
            "consumo_km_litro": p.consumo_km_litro,
            "costo_variabile_km": p.costo_variabile_km,
            "costo_autista_ora": p.costo_autista_ora,
            "costo_fisso_giorno": p.costo_fisso_giorno,
        }
        for p in sorted(PROFILI_VEICOLO.values(), key=lambda x: x.portata_kg)
    ]


@router.get("/vettori")
def elenco_vettori() -> list[dict]:
    return db.query("SELECT * FROM vettori ORDER BY nome")


# ------------------------------------------------------------------ ordini
@router.get("/ordini")
def elenco_ordini(
    stato: str | None = None,
    data_da: str | None = None,
    data_a: str | None = None,
    limite: int = Query(default=200, le=1000),
) -> list[dict]:
    condizioni, parametri = [], []
    if stato:
        condizioni.append("o.stato = ?")
        parametri.append(stato)
    if data_da:
        condizioni.append("o.data_richiesta >= ?")
        parametri.append(data_da)
    if data_a:
        condizioni.append("o.data_richiesta <= ?")
        parametri.append(data_a)
    dove = f"WHERE {' AND '.join(condizioni)}" if condizioni else ""
    ordini = db.query(
        f"""SELECT o.*, so.codice AS origine_codice, so.nome AS origine_nome,
                   sd.codice AS destino_codice, sd.nome AS destino_nome,
                   sd.comune AS destino_comune, sd.provincia AS destino_provincia
            FROM ordini o
            LEFT JOIN siti so ON so.id = o.origine_id
            JOIN siti sd ON sd.id = o.destino_id
            {dove}
            ORDER BY o.data_richiesta, o.priorita LIMIT ?""",
        (*parametri, limite),
    )
    if not ordini:
        return []
    identificativi = ",".join(str(o["id"]) for o in ordini)
    righe = db.query(
        f"""SELECT r.*, a.codice AS articolo_codice, a.descrizione AS articolo_descrizione,
                   a.peso_kg, a.volume_m3, a.pezzi_per_pallet
            FROM ordini_righe r JOIN articoli a ON a.id = r.articolo_id
            WHERE r.ordine_id IN ({identificativi})"""
    )
    per_ordine: dict[int, list[dict]] = {}
    for r in righe:
        r["peso_totale_kg"] = round(r["quantita"] * r["peso_kg"], 1)
        r["volume_totale_m3"] = round(r["quantita"] * r["volume_m3"], 3)
        per_ordine.setdefault(r["ordine_id"], []).append(r)
    for o in ordini:
        o["righe"] = per_ordine.get(o["id"], [])
        o["peso_kg"] = round(sum(r["peso_totale_kg"] for r in o["righe"]), 1)
        o["volume_m3"] = round(sum(r["volume_totale_m3"] for r in o["righe"]), 3)
    return ordini


@router.post("/ordini", status_code=201)
def crea_ordine(dati: OrdineInput) -> dict:
    for sito_id in (dati.origine_id, dati.destino_id):
        if not db.query_uno("SELECT id FROM siti WHERE id = ?", (sito_id,)):
            raise HTTPException(404, f"Sito inesistente: {sito_id}")
    riferimento = dati.riferimento
    if not riferimento:
        progressivo = db.query_uno("SELECT COUNT(*) AS n FROM ordini")["n"] + 1
        riferimento = f"ORD-{date.today().year}-{progressivo:05d}"
    if db.query_uno("SELECT id FROM ordini WHERE riferimento = ?", (riferimento,)):
        raise HTTPException(409, f"Riferimento ordine gia' presente: {riferimento}")

    with db.transazione() as conn:
        cur = conn.execute(
            """INSERT INTO ordini (riferimento,tipo,origine_id,destino_id,data_richiesta,priorita,note)
               VALUES (?,?,?,?,?,?,?)""",
            (
                riferimento,
                dati.tipo,
                dati.origine_id,
                dati.destino_id,
                dati.data_richiesta,
                dati.priorita,
                dati.note,
            ),
        )
        ordine_id = cur.lastrowid
        for riga in dati.righe:
            if not conn.execute(
                "SELECT id FROM articoli WHERE id = ?", (riga.articolo_id,)
            ).fetchone():
                raise HTTPException(404, f"Articolo inesistente: {riga.articolo_id}")
            conn.execute(
                "INSERT INTO ordini_righe (ordine_id,articolo_id,quantita) VALUES (?,?,?)",
                (ordine_id, riga.articolo_id, riga.quantita),
            )
    return db.query_uno("SELECT * FROM ordini WHERE id = ?", (ordine_id,))


@router.patch("/ordini/{ordine_id}/stato")
def aggiorna_stato_ordine(ordine_id: int, stato: str) -> dict:
    validi = ("DA_PIANIFICARE", "PIANIFICATO", "IN_TRANSITO", "CONSEGNATO", "ANNULLATO")
    if stato not in validi:
        raise HTTPException(422, f"Stato non valido. Ammessi: {', '.join(validi)}")
    if not db.query_uno("SELECT id FROM ordini WHERE id = ?", (ordine_id,)):
        raise HTTPException(404, "Ordine non trovato")
    db.esegui("UPDATE ordini SET stato = ? WHERE id = ?", (stato, ordine_id))
    return db.query_uno("SELECT * FROM ordini WHERE id = ?", (ordine_id,))
