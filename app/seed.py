"""Popolamento del database con una rete logistica italiana dimostrativa.

Lo scenario rappresenta un gruppo manifatturiero con tre stabilimenti
produttivi, cinque depositi/piattaforme distributive e una base clienti
distribuita su tutta la penisola.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from . import db

# (codice, nome, tipo, indirizzo, comune, provincia, cap, regione, lat, lon,
#  capacita_pallet, apertura, chiusura, baie)
SITI = [
    # --- Stabilimenti produttivi -------------------------------------------
    ("ST-BS", "Stabilimento Brescia Ovest", "STABILIMENTO", "Via dell'Industria 44", "Brescia", "BS", "25125", "Lombardia", 45.5416, 10.2118, 4200, 6.0, 20.0, 6),
    ("ST-MO", "Stabilimento Modena Nord", "STABILIMENTO", "Strada Statale 12, 88", "Modena", "MO", "41122", "Emilia-Romagna", 44.6471, 10.9252, 3600, 6.0, 20.0, 5),
    ("ST-VI", "Stabilimento Vicenza Est", "STABILIMENTO", "Viale della Meccanica 7", "Vicenza", "VI", "36100", "Veneto", 45.5455, 11.5354, 2800, 6.0, 18.0, 4),
    # --- Depositi e piattaforme -------------------------------------------
    ("DP-MI", "Deposito Milano Pioltello", "DEPOSITO", "Via Lombardia 12", "Pioltello", "MI", "20096", "Lombardia", 45.5031, 9.3320, 5200, 7.0, 19.0, 8),
    ("DP-BO", "Piattaforma Interporto Bologna", "DEPOSITO", "Interporto, Blocco 4", "Bentivoglio", "BO", "40010", "Emilia-Romagna", 44.6350, 11.3390, 6000, 6.0, 20.0, 10),
    ("DP-RM", "Deposito Roma Pomezia", "DEPOSITO", "Via Pontina km 30", "Pomezia", "RM", "00071", "Lazio", 41.6690, 12.5030, 4000, 7.0, 18.0, 6),
    ("DP-NA", "Piattaforma Interporto Nola", "DEPOSITO", "Interporto Campano, Lotto 12", "Nola", "NA", "80035", "Campania", 40.9160, 14.5290, 3500, 7.0, 18.0, 5),
    ("CD-BA", "Cross-dock Bari Modugno", "CROSSDOCK", "Zona ASI Modugno", "Modugno", "BA", "70026", "Puglia", 41.0870, 16.7790, 900, 7.0, 17.0, 3),
    # --- Clienti -----------------------------------------------------------
    ("CL-TO1", "Meccanica Subalpina", "CLIENTE", "Corso Francia 210", "Torino", "TO", "10146", "Piemonte", 45.0703, 7.6869, 0, 8.0, 17.0, 1),
    ("CL-NO1", "Novara Impianti", "CLIENTE", "Via Biella 5", "Novara", "NO", "28100", "Piemonte", 45.4469, 8.6216, 0, 8.0, 16.5, 1),
    ("CL-BG1", "Bergamo Automazioni", "CLIENTE", "Via Zanica 88", "Bergamo", "BG", "24126", "Lombardia", 45.6983, 9.6773, 0, 8.0, 17.5, 1),
    ("CL-MN1", "Mantova Agri Service", "CLIENTE", "Viale Fiera 3", "Mantova", "MN", "46100", "Lombardia", 45.1564, 10.7914, 0, 8.5, 16.0, 1),
    ("CL-VR1", "Verona Tecno Sistemi", "CLIENTE", "Via Torbido 19", "Verona", "VR", "37135", "Veneto", 45.4384, 10.9916, 0, 8.0, 18.0, 1),
    ("CL-VE1", "Laguna Componenti", "CLIENTE", "Via Torino 240", "Venezia", "VE", "30172", "Veneto", 45.4870, 12.2400, 0, 8.0, 17.0, 1),
    ("CL-TS1", "Adriatico Industriale", "CLIENTE", "Zona Industriale 21", "Trieste", "TS", "34147", "Friuli-Venezia Giulia", 45.6495, 13.7768, 0, 8.0, 16.0, 1),
    ("CL-GE1", "Liguria Marine Parts", "CLIENTE", "Via San Benedetto 9", "Genova", "GE", "16149", "Liguria", 44.4056, 8.9463, 0, 8.0, 17.0, 1),
    ("CL-PR1", "Parma Food Machinery", "CLIENTE", "Via Emilia Ovest 130", "Parma", "PR", "43126", "Emilia-Romagna", 44.8015, 10.3279, 0, 8.0, 17.5, 1),
    ("CL-RE1", "Reggio Meccanica", "CLIENTE", "Via Gramsci 44", "Reggio nell'Emilia", "RE", "42124", "Emilia-Romagna", 44.6980, 10.6310, 0, 8.0, 17.0, 1),
    ("CL-RN1", "Romagna Packaging", "CLIENTE", "Via Emilia 512", "Rimini", "RN", "47922", "Emilia-Romagna", 44.0678, 12.5695, 0, 8.5, 16.5, 1),
    ("CL-FI1", "Toscana Precision", "CLIENTE", "Via Pistoiese 77", "Firenze", "FI", "50145", "Toscana", 43.7696, 11.2558, 0, 8.0, 17.0, 1),
    ("CL-PI1", "Pisa Aerospace Supply", "CLIENTE", "Via Aurelia 210", "Pisa", "PI", "56121", "Toscana", 43.7228, 10.4017, 0, 8.5, 16.0, 1),
    ("CL-AN1", "Marche Utensili", "CLIENTE", "Via Flaminia 300", "Ancona", "AN", "60126", "Marche", 43.6158, 13.5189, 0, 8.0, 17.0, 1),
    ("CL-PG1", "Umbria Sistemi", "CLIENTE", "Via Corcianese 12", "Perugia", "PG", "06127", "Umbria", 43.1107, 12.3908, 0, 8.0, 16.5, 1),
    ("CL-RM1", "Capitale Impianti", "CLIENTE", "Via Tiburtina 1120", "Roma", "RM", "00156", "Lazio", 41.9028, 12.4964, 0, 8.0, 17.0, 1),
    ("CL-RM2", "Lazio Energia Servizi", "CLIENTE", "Via Ardeatina 200", "Roma", "RM", "00134", "Lazio", 41.7800, 12.5100, 0, 9.0, 16.0, 1),
    ("CL-PE1", "Abruzzo Metalmeccanica", "CLIENTE", "Via Tiburtina Valeria 40", "Pescara", "PE", "65128", "Abruzzo", 42.4618, 14.2161, 0, 8.0, 16.5, 1),
    ("CL-NA1", "Partenope Industrie", "CLIENTE", "Via Argine 900", "Napoli", "NA", "80147", "Campania", 40.8518, 14.2681, 0, 8.0, 16.0, 1),
    ("CL-SA1", "Salerno Logistica Industriale", "CLIENTE", "Zona Industriale", "Salerno", "SA", "84131", "Campania", 40.6824, 14.7681, 0, 8.0, 16.0, 1),
    ("CL-BA1", "Puglia Sistemi Idraulici", "CLIENTE", "Via Napoli 320", "Bari", "BA", "70123", "Puglia", 41.1171, 16.8719, 0, 8.0, 16.5, 1),
    ("CL-LE1", "Salento Industrie", "CLIENTE", "Via Monteroni", "Lecce", "LE", "73100", "Puglia", 40.3515, 18.1750, 0, 8.5, 15.5, 1),
    ("CL-CS1", "Calabria Impianti", "CLIENTE", "Contrada Lecco", "Cosenza", "CS", "87100", "Calabria", 39.2983, 16.2539, 0, 8.5, 15.5, 1),
    ("CL-CT1", "Etna Meccanica", "CLIENTE", "Zona Industriale, VI Strada", "Catania", "CT", "95121", "Sicilia", 37.5079, 15.0830, 0, 8.0, 16.0, 1),
    ("CL-PA1", "Sicilia Ovest Forniture", "CLIENTE", "Via Ugo La Malfa 100", "Palermo", "PA", "90146", "Sicilia", 38.1157, 13.3615, 0, 8.0, 16.0, 1),
    ("CL-CA1", "Sardegna Tecnica", "CLIENTE", "Viale Elmas 142", "Cagliari", "CA", "09122", "Sardegna", 39.2238, 9.1217, 0, 8.5, 15.5, 1),
]

# (codice, descrizione, famiglia, peso_kg, volume_m3, pezzi_pallet, valore, abc,
#  adr, sovrapponibile, temp_controllata, codice_sito_produttore)
ARTICOLI = [
    ("MOT-0100", "Motoriduttore serie 100", "Motoriduttori", 18.5, 0.028, 40, 210.0, "A", 0, 1, 0, "ST-BS"),
    ("MOT-0200", "Motoriduttore serie 200 rinforzato", "Motoriduttori", 31.0, 0.045, 24, 385.0, "A", 0, 0, 0, "ST-BS"),
    ("POM-0310", "Pompa idraulica 31 l/min", "Idraulica", 12.4, 0.019, 60, 168.0, "A", 0, 1, 0, "ST-MO"),
    ("POM-0450", "Pompa idraulica 45 l/min", "Idraulica", 16.8, 0.024, 48, 236.0, "B", 0, 1, 0, "ST-MO"),
    ("VAL-0110", "Valvola proporzionale DN25", "Idraulica", 3.2, 0.006, 200, 92.0, "B", 0, 1, 0, "ST-MO"),
    ("QDR-0500", "Quadro elettrico di comando", "Elettrico", 46.0, 0.180, 8, 640.0, "A", 0, 0, 0, "ST-VI"),
    ("SEN-0080", "Sensore di posizione induttivo", "Elettronica", 0.4, 0.001, 900, 38.0, "B", 0, 1, 0, "ST-VI"),
    ("CAV-0025", "Cavo di potenza schermato 25 m", "Elettrico", 21.0, 0.030, 36, 74.0, "C", 0, 1, 0, "ST-VI"),
    ("TEL-0700", "Telaio saldato serie 700", "Carpenteria", 128.0, 0.520, 4, 890.0, "B", 0, 0, 0, "ST-BS"),
    ("CUS-0040", "Kit cuscinetti di ricambio", "Ricambi", 2.6, 0.004, 300, 46.0, "C", 0, 1, 0, "ST-MO"),
    ("OLI-0020", "Olio idraulico ISO VG46 - fusto 20 l", "Materiali di consumo", 18.2, 0.024, 32, 58.0, "C", 1, 0, 0, "ST-MO"),
    ("VER-0005", "Vernice bicomponente industriale 5 l", "Materiali di consumo", 5.6, 0.007, 96, 41.0, "C", 1, 1, 0, "ST-BS"),
]

VETTORI = [
    ("Trasporti Padani S.r.l.", "IT01234560981", 0.14, 34.0, 0.06, "Nord Italia", 1, 96.5),
    ("Adriatica Logistica S.p.A.", "IT02233440429", 0.09, 36.0, 0.07, "Centro e Adriatico", 2, 94.0),
    ("Corriere Meridione S.r.l.", "IT03344550722", 0.06, 38.0, 0.07, "Sud e Isole", 3, 91.5),
    ("Italexpress Groupage", "IT04455660152", 0.18, 32.0, 0.055, "Nazionale", 2, 93.0),
]

# (targa, profilo, codice sito base, adr)
VEICOLI = [
    ("GA123AB", "BILICO", "ST-BS", 0),
    ("GB456CD", "BILICO", "ST-BS", 1),
    ("GC789EF", "AUTOTRENO", "ST-MO", 0),
    ("GD012GH", "AUTOTRENO", "ST-VI", 0),
    ("GE345IL", "MOTRICE_180", "DP-MI", 0),
    ("GF678MN", "MOTRICE_180", "DP-MI", 0),
    ("GG901OP", "MOTRICE_180", "DP-BO", 0),
    ("GH234QR", "MOTRICE_180", "DP-BO", 1),
    ("GI567ST", "MOTRICE_75", "DP-RM", 0),
    ("GL890UV", "MOTRICE_75", "DP-NA", 0),
    ("GM123XY", "FURGONE", "DP-MI", 0),
    ("GN456ZA", "FURGONE", "DP-RM", 0),
]


def _svuota(conn) -> None:
    for tabella in (
        "consegne",
        "piani",
        "ordini_righe",
        "ordini",
        "giacenze",
        "veicoli",
        "vettori",
        "articoli",
        "siti",
    ):
        conn.execute(f"DELETE FROM {tabella}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tabella,))


def popola(seed: int = 42) -> dict:
    """Ricrea lo schema e carica lo scenario dimostrativo."""
    rnd = random.Random(seed)
    db.inizializza()

    with db.transazione() as conn:
        _svuota(conn)

        for s in SITI:
            conn.execute(
                """INSERT INTO siti (codice,nome,tipo,indirizzo,comune,provincia,cap,regione,
                                     lat,lon,capacita_pallet,apertura,chiusura,baie_carico)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                s,
            )

        siti_per_codice = {
            r["codice"]: r["id"] for r in conn.execute("SELECT id, codice FROM siti")
        }

        for a in ARTICOLI:
            conn.execute(
                """INSERT INTO articoli (codice,descrizione,famiglia,peso_kg,volume_m3,
                       pezzi_per_pallet,valore_unitario,classe_abc,adr,sovrapponibile,
                       temperatura_controllata,sito_produttore)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*a[:-1], siti_per_codice[a[-1]]),
            )

        for v in VETTORI:
            conn.execute(
                """INSERT INTO vettori (nome,partita_iva,sconto_pct,minimo_fatturabile,
                       supplemento_carburante_pct,aree_servite,lead_time_giorni,puntualita_pct)
                   VALUES (?,?,?,?,?,?,?,?)""",
                v,
            )

        for targa, profilo, sito, adr in VEICOLI:
            conn.execute(
                "INSERT INTO veicoli (targa,profilo,sito_base,adr_abilitato) VALUES (?,?,?,?)",
                (targa, profilo, siti_per_codice[sito], adr),
            )

        # --- Giacenze sui siti interni ------------------------------------
        articoli = [dict(r) for r in conn.execute("SELECT * FROM articoli")]
        siti_interni = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM siti WHERE tipo IN ('STABILIMENTO','DEPOSITO','CROSSDOCK')"
            )
        ]
        for sito in siti_interni:
            for art in articoli:
                # I depositi tengono a stock soprattutto le classi A e B.
                if sito["tipo"] == "CROSSDOCK" and art["classe_abc"] == "C":
                    continue
                base = {"A": 90.0, "B": 45.0, "C": 18.0}[art["classe_abc"]]
                fattore_sito = {"STABILIMENTO": 1.4, "DEPOSITO": 1.0, "CROSSDOCK": 0.3}[sito["tipo"]]
                domanda = round(base * fattore_sito * rnd.uniform(0.55, 1.5), 1)
                deviazione = round(domanda * rnd.uniform(0.18, 0.42), 1)
                lead = 1.0 if sito["tipo"] == "STABILIMENTO" else rnd.choice([2.0, 3.0, 4.0])
                copertura = rnd.uniform(1.5, 16.0)
                conn.execute(
                    """INSERT INTO giacenze (sito_id,articolo_id,quantita,impegnata,scorta_massima,
                           domanda_media_giorno,deviazione_domanda,lead_time_giorni,
                           deviazione_lead_time,livello_servizio)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sito["id"],
                        art["id"],
                        round(domanda * copertura, 0),
                        round(domanda * rnd.uniform(0, 0.8), 0),
                        round(domanda * 28, 0),
                        domanda,
                        deviazione,
                        lead,
                        round(rnd.uniform(0.2, 1.1), 2),
                        0.97 if art["classe_abc"] == "A" else 0.95,
                    ),
                )

        # --- Ordini cliente da pianificare ---------------------------------
        clienti = [dict(r) for r in conn.execute("SELECT * FROM siti WHERE tipo='CLIENTE'")]
        depositi = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM siti WHERE tipo IN ('DEPOSITO','CROSSDOCK','STABILIMENTO')"
            )
        ]
        oggi = date.today()
        progressivo = 1
        for giorno in range(5):
            data_richiesta = (oggi + timedelta(days=giorno + 1)).isoformat()
            for cliente in clienti:
                if rnd.random() > 0.55:
                    continue
                # Il deposito di partenza e' il piu' vicino al cliente.
                origine = min(
                    depositi,
                    key=lambda d: (d["lat"] - cliente["lat"]) ** 2
                    + (d["lon"] - cliente["lon"]) ** 2,
                )
                conn.execute(
                    """INSERT INTO ordini (riferimento,tipo,origine_id,destino_id,data_richiesta,priorita,stato)
                       VALUES (?,?,?,?,?,?,'DA_PIANIFICARE')""",
                    (
                        f"ORD-{oggi.year}-{progressivo:05d}",
                        "CLIENTE",
                        origine["id"],
                        cliente["id"],
                        data_richiesta,
                        rnd.choice([1, 3, 5, 5, 5, 8]),
                    ),
                )
                ordine_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                for art in rnd.sample(articoli, rnd.randint(1, 4)):
                    quantita = max(
                        1,
                        int(art["pezzi_per_pallet"] * rnd.uniform(0.15, 2.2)),
                    )
                    conn.execute(
                        "INSERT INTO ordini_righe (ordine_id,articolo_id,quantita) VALUES (?,?,?)",
                        (ordine_id, art["id"], quantita),
                    )
                progressivo += 1

        conteggi = {
            tabella: conn.execute(f"SELECT COUNT(*) AS n FROM {tabella}").fetchone()["n"]
            for tabella in ("siti", "articoli", "giacenze", "veicoli", "vettori", "ordini", "ordini_righe")
        }

    return conteggi


if __name__ == "__main__":
    print(popola())
