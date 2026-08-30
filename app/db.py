"""Accesso al database SQLite della piattaforma.

Si usa direttamente ``sqlite3``: lo schema e' compatto e non giustifica un
ORM. Le righe sono restituite come dizionari per essere serializzate
direttamente dalle API.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

PERCORSO_DB = os.environ.get(
    "LOGISTICMASTER_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "logisticmaster.db")
)

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS siti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codice TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('STABILIMENTO','DEPOSITO','CROSSDOCK','CLIENTE','FORNITORE')),
    indirizzo TEXT,
    comune TEXT NOT NULL,
    provincia TEXT NOT NULL,
    cap TEXT,
    regione TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    capacita_pallet INTEGER DEFAULT 0,
    apertura REAL DEFAULT 8.0,
    chiusura REAL DEFAULT 18.0,
    baie_carico INTEGER DEFAULT 1,
    attivo INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articoli (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codice TEXT NOT NULL UNIQUE,
    descrizione TEXT NOT NULL,
    famiglia TEXT,
    um TEXT DEFAULT 'PZ',
    peso_kg REAL NOT NULL DEFAULT 1.0,
    volume_m3 REAL NOT NULL DEFAULT 0.001,
    pezzi_per_pallet REAL NOT NULL DEFAULT 100,
    valore_unitario REAL NOT NULL DEFAULT 1.0,
    classe_abc TEXT DEFAULT 'C',
    adr INTEGER DEFAULT 0,
    sovrapponibile INTEGER DEFAULT 1,
    temperatura_controllata INTEGER DEFAULT 0,
    sito_produttore INTEGER REFERENCES siti(id)
);

CREATE TABLE IF NOT EXISTS giacenze (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sito_id INTEGER NOT NULL REFERENCES siti(id),
    articolo_id INTEGER NOT NULL REFERENCES articoli(id),
    quantita REAL NOT NULL DEFAULT 0,
    impegnata REAL NOT NULL DEFAULT 0,
    scorta_massima REAL NOT NULL DEFAULT 0,
    domanda_media_giorno REAL NOT NULL DEFAULT 0,
    deviazione_domanda REAL NOT NULL DEFAULT 0,
    lead_time_giorni REAL NOT NULL DEFAULT 3,
    deviazione_lead_time REAL NOT NULL DEFAULT 0.5,
    livello_servizio REAL NOT NULL DEFAULT 0.95,
    UNIQUE (sito_id, articolo_id)
);

CREATE TABLE IF NOT EXISTS veicoli (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    targa TEXT NOT NULL UNIQUE,
    profilo TEXT NOT NULL,
    sito_base INTEGER NOT NULL REFERENCES siti(id),
    adr_abilitato INTEGER DEFAULT 0,
    disponibile INTEGER DEFAULT 1,
    note TEXT
);

CREATE TABLE IF NOT EXISTS vettori (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    partita_iva TEXT,
    sconto_pct REAL DEFAULT 0,
    minimo_fatturabile REAL DEFAULT 32,
    supplemento_carburante_pct REAL DEFAULT 0.06,
    aree_servite TEXT,
    lead_time_giorni REAL DEFAULT 2,
    puntualita_pct REAL DEFAULT 95
);

CREATE TABLE IF NOT EXISTS ordini (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    riferimento TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL CHECK (tipo IN ('CLIENTE','TRASFERIMENTO','FORNITORE')),
    origine_id INTEGER REFERENCES siti(id),
    destino_id INTEGER NOT NULL REFERENCES siti(id),
    data_richiesta TEXT NOT NULL,
    priorita INTEGER DEFAULT 5,
    stato TEXT NOT NULL DEFAULT 'DA_PIANIFICARE'
        CHECK (stato IN ('DA_PIANIFICARE','PIANIFICATO','IN_TRANSITO','CONSEGNATO','ANNULLATO')),
    note TEXT
);

CREATE TABLE IF NOT EXISTS ordini_righe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ordine_id INTEGER NOT NULL REFERENCES ordini(id) ON DELETE CASCADE,
    articolo_id INTEGER NOT NULL REFERENCES articoli(id),
    quantita REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS piani (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creato_il TEXT NOT NULL,
    data_riferimento TEXT NOT NULL,
    descrizione TEXT,
    parametri TEXT,
    risultato TEXT NOT NULL
);

-- Esecuzione: dal piano nascono i viaggi, che si eseguono tappa per tappa.
CREATE TABLE IF NOT EXISTS viaggi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    piano_id INTEGER REFERENCES piani(id) ON DELETE CASCADE,
    giro_id TEXT NOT NULL,
    data TEXT NOT NULL,
    origine_id INTEGER NOT NULL REFERENCES siti(id),
    profilo TEXT NOT NULL,
    veicolo_id INTEGER REFERENCES veicoli(id),
    vettore_id INTEGER REFERENCES vettori(id),
    autista TEXT,
    stato TEXT NOT NULL DEFAULT 'PIANIFICATO'
        CHECK (stato IN ('PIANIFICATO','ASSEGNATO','IN_CORSO','COMPLETATO','ANNULLATO')),
    esecuzione TEXT NOT NULL DEFAULT 'PROPRIO' CHECK (esecuzione IN ('PROPRIO','TERZI')),
    km_previsti REAL DEFAULT 0,
    ore_previste REAL DEFAULT 0,
    giorni_previsti REAL DEFAULT 1,
    costo_previsto REAL DEFAULT 0,
    partenza_prevista REAL DEFAULT 6,
    partenza_effettiva TEXT,
    rientro_effettivo TEXT,
    km_effettivi REAL,
    costo_effettivo REAL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS viaggi_tappe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    viaggio_id INTEGER NOT NULL REFERENCES viaggi(id) ON DELETE CASCADE,
    sequenza INTEGER NOT NULL,
    sito_id INTEGER NOT NULL REFERENCES siti(id),
    data_prevista TEXT NOT NULL,
    ora_prevista REAL NOT NULL,
    data_effettiva TEXT,
    ora_effettiva REAL,
    stato TEXT NOT NULL DEFAULT 'DA_ESEGUIRE'
        CHECK (stato IN ('DA_ESEGUIRE','CONSEGNATA','PARZIALE','RIFIUTATA','NON_ESEGUITA')),
    causale TEXT,
    note TEXT,
    UNIQUE (viaggio_id, sequenza)
);

CREATE TABLE IF NOT EXISTS tappe_righe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tappa_id INTEGER NOT NULL REFERENCES viaggi_tappe(id) ON DELETE CASCADE,
    ordine_id INTEGER NOT NULL REFERENCES ordini(id),
    articolo_id INTEGER NOT NULL REFERENCES articoli(id),
    quantita_richiesta REAL NOT NULL,
    quantita_consegnata REAL
);

CREATE TABLE IF NOT EXISTS viaggi_eventi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    viaggio_id INTEGER NOT NULL REFERENCES viaggi(id) ON DELETE CASCADE,
    tappa_id INTEGER REFERENCES viaggi_tappe(id) ON DELETE CASCADE,
    momento TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descrizione TEXT
);

CREATE INDEX IF NOT EXISTS idx_giacenze_sito ON giacenze(sito_id);
CREATE INDEX IF NOT EXISTS idx_righe_ordine ON ordini_righe(ordine_id);
CREATE INDEX IF NOT EXISTS idx_ordini_stato ON ordini(stato, data_richiesta);
CREATE INDEX IF NOT EXISTS idx_viaggi_stato ON viaggi(stato, data);
CREATE INDEX IF NOT EXISTS idx_tappe_viaggio ON viaggi_tappe(viaggio_id, sequenza);
CREATE INDEX IF NOT EXISTS idx_righe_tappa ON tappe_righe(tappa_id);
CREATE INDEX IF NOT EXISTS idx_eventi_viaggio ON viaggi_eventi(viaggio_id, momento);
"""


def connessione() -> sqlite3.Connection:
    """Apre una connessione con row factory a dizionario."""
    conn = sqlite3.connect(PERCORSO_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transazione() -> Iterator[sqlite3.Connection]:
    """Contesto transazionale: commit in uscita, rollback su eccezione."""
    conn = connessione()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inizializza() -> None:
    """Crea lo schema se non presente."""
    with transazione() as conn:
        conn.executescript(SCHEMA)


def query(sql: str, parametri: tuple | dict = ()) -> list[dict[str, Any]]:
    """Esegue una SELECT e restituisce una lista di dizionari."""
    conn = connessione()
    try:
        return [dict(r) for r in conn.execute(sql, parametri).fetchall()]
    finally:
        conn.close()


def query_uno(sql: str, parametri: tuple | dict = ()) -> dict[str, Any] | None:
    risultati = query(sql, parametri)
    return risultati[0] if risultati else None


def esegui(sql: str, parametri: tuple | dict = ()) -> int:
    """Esegue una INSERT/UPDATE/DELETE e restituisce lastrowid o rowcount."""
    with transazione() as conn:
        cur = conn.execute(sql, parametri)
        return cur.lastrowid if cur.lastrowid else cur.rowcount
