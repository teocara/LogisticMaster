"""Verifiche dell'esecuzione dei viaggi e del calcolo OTIF a consuntivo."""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest


class BaseEsecuzione(unittest.TestCase):
    """Predispone un database temporaneo con un piano gia' salvato."""

    @classmethod
    def setUpClass(cls):
        cls.cartella = tempfile.TemporaryDirectory()
        os.environ["LOGISTICMASTER_DB"] = os.path.join(cls.cartella.name, "esecuzione.db")

        from app import db

        importlib.reload(db)
        from app import seed

        importlib.reload(seed)
        seed.popola(seed=5)

        from app.core import esecuzione, otif, pianificazione

        cls.esecuzione, cls.otif, cls.db = esecuzione, otif, db
        piano = pianificazione.genera_piano()
        cls.piano_id = pianificazione.salva_piano(piano, "Piano di prova")
        cls.piano = piano

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()
        os.environ.pop("LOGISTICMASTER_DB", None)

    def viaggio_pianificato(self) -> dict:
        viaggi = self.esecuzione.elenco_viaggi(stato="PIANIFICATO", limite=1000)
        self.assertTrue(viaggi, "Nessun viaggio disponibile per la prova")
        return self.esecuzione.dettaglio_viaggio(viaggi[0]["id"])

    def esegui_viaggio(self, viaggio: dict, **esito) -> dict:
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"], f"{viaggio['data']}T06:00:00")
        for tappa in viaggio["tappe"]:
            self.esecuzione.registra_esito_tappa(
                tappa["id"],
                esito.get("data_effettiva", tappa["data_prevista"]),
                esito.get("ora_effettiva", tappa["ora_prevista"]),
                esito.get("quantita", {}),
                esito.get("causale"),
                non_eseguita=esito.get("non_eseguita", False),
            )
        return self.esecuzione.dettaglio_viaggio(viaggio["id"])


class TestCreazioneViaggi(BaseEsecuzione):
    def test_ogni_giro_del_piano_genera_un_viaggio(self):
        viaggi = self.esecuzione.elenco_viaggi(limite=1000)
        self.assertEqual(len(viaggi), len(self.piano["giri"]))
        self.assertEqual({v["giro_id"] for v in viaggi}, {g["id"] for g in self.piano["giri"]})

    def test_le_tappe_ricalcano_le_fermate_del_giro(self):
        viaggio = self.viaggio_pianificato()
        giro = next(g for g in self.piano["giri"] if g["id"] == viaggio["giro_id"])
        self.assertEqual([t["sito_id"] for t in viaggio["tappe"]], giro["sequenza"])
        self.assertTrue(all(t["righe"] for t in viaggio["tappe"]))

    def test_le_righe_da_consegnare_corrispondono_agli_ordini(self):
        viaggio = self.viaggio_pianificato()
        for tappa in viaggio["tappe"]:
            for riga in tappa["righe"]:
                atteso = self.db.query_uno(
                    """SELECT quantita FROM ordini_righe
                       WHERE ordine_id = ? AND articolo_id = ?""",
                    (riga["ordine_id"], riga["articolo_id"]),
                )
                self.assertAlmostEqual(riga["quantita_richiesta"], atteso["quantita"])

    def test_i_viaggi_multigiorno_hanno_tappe_su_date_diverse(self):
        multigiorno = [
            v for v in self.esecuzione.elenco_viaggi(limite=1000) if v["giorni_previsti"] > 1
        ]
        self.assertTrue(multigiorno, "Lo scenario deve contenere almeno un viaggio su piu' giorni")
        viaggio = self.esecuzione.dettaglio_viaggio(multigiorno[0]["id"])
        self.assertGreater(len({t["data_prevista"] for t in viaggio["tappe"]}), 1)


class TestAvanzamento(BaseEsecuzione):
    def test_sequenza_completa_di_stati(self):
        viaggio = self.viaggio_pianificato()
        self.assertEqual(self.esecuzione.assegna(viaggio["id"], vettore_id=1)["stato"], "ASSEGNATO")
        self.assertEqual(self.esecuzione.registra_partenza(viaggio["id"])["stato"], "IN_CORSO")
        for tappa in viaggio["tappe"]:
            self.esecuzione.registra_esito_tappa(tappa["id"], tappa["data_prevista"], tappa["ora_prevista"])
        chiuso = self.esecuzione.chiudi_viaggio(viaggio["id"], km_effettivi=100, costo_effettivo=250)
        self.assertEqual(chiuso["stato"], "COMPLETATO")
        self.assertEqual(chiuso["km_effettivi"], 100)
        self.assertAlmostEqual(chiuso["scostamento_costo"], 250 - viaggio["costo_previsto"], places=2)

    def test_non_si_parte_senza_assegnazione(self):
        viaggio = self.viaggio_pianificato()
        with self.assertRaises(self.esecuzione.ErroreEsecuzione):
            self.esecuzione.registra_partenza(viaggio["id"])

    def test_non_si_registra_un_esito_prima_della_partenza(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        with self.assertRaises(self.esecuzione.ErroreEsecuzione):
            self.esecuzione.registra_esito_tappa(
                viaggio["tappe"][0]["id"], viaggio["data"], 9.0
            )

    def test_non_si_chiude_con_tappe_aperte(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        with self.assertRaises(self.esecuzione.ErroreEsecuzione) as contesto:
            self.esecuzione.chiudi_viaggio(viaggio["id"])
        self.assertIn("tappe", str(contesto.exception))

    def test_assegnazione_ambigua_rifiutata(self):
        viaggio = self.viaggio_pianificato()
        with self.assertRaises(self.esecuzione.ErroreEsecuzione):
            self.esecuzione.assegna(viaggio["id"], veicolo_id=1, vettore_id=1)
        with self.assertRaises(self.esecuzione.ErroreEsecuzione):
            self.esecuzione.assegna(viaggio["id"])

    def test_lo_stesso_mezzo_non_puo_fare_due_viaggi_in_giornata(self):
        viaggi = [
            self.esecuzione.dettaglio_viaggio(v["id"])
            for v in self.esecuzione.elenco_viaggi(stato="PIANIFICATO", limite=1000)
        ]
        primo = viaggi[0]
        secondo = next(v for v in viaggi[1:] if v["data"] == primo["data"])
        self.esecuzione.assegna(primo["id"], veicolo_id=1)
        with self.assertRaises(self.esecuzione.ErroreEsecuzione) as contesto:
            self.esecuzione.assegna(secondo["id"], veicolo_id=1)
        self.assertIn("impegnato", str(contesto.exception))

    def test_quantita_superiore_alla_richiesta_rifiutata(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        tappa = viaggio["tappe"][0]
        riga = tappa["righe"][0]
        with self.assertRaises(self.esecuzione.ErroreEsecuzione):
            self.esecuzione.registra_esito_tappa(
                tappa["id"], tappa["data_prevista"], 10.0, {riga["id"]: riga["quantita_richiesta"] + 1}
            )

    def test_causale_sconosciuta_rifiutata(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        with self.assertRaises(self.esecuzione.ErroreEsecuzione):
            self.esecuzione.registra_esito_tappa(
                viaggio["tappe"][0]["id"], viaggio["data"], 10.0, causale="SCIOPERO_MARZIANI"
            )

    def test_consegna_parziale_marca_la_tappa_e_lascia_l_ordine_aperto(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        tappa = viaggio["tappe"][0]
        riga = tappa["righe"][0]
        esito = self.esecuzione.registra_esito_tappa(
            tappa["id"],
            tappa["data_prevista"],
            tappa["ora_prevista"],
            {riga["id"]: riga["quantita_richiesta"] / 2},
            causale="MERCE_MANCANTE",
        )
        self.assertEqual(esito["stato"], "PARZIALE")
        ordine = self.db.query_uno("SELECT stato FROM ordini WHERE id = ?", (riga["ordine_id"],))
        self.assertEqual(ordine["stato"], "IN_TRANSITO")

    def test_tappa_non_eseguita_azzera_le_quantita(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        tappa = viaggio["tappe"][0]
        esito = self.esecuzione.registra_esito_tappa(
            tappa["id"], tappa["data_prevista"], tappa["ora_prevista"],
            causale="SITO_CHIUSO", non_eseguita=True,
        )
        self.assertEqual(esito["stato"], "NON_ESEGUITA")
        self.assertTrue(all(r["quantita_consegnata"] == 0 for r in esito["righe"]))

    def test_annullamento_riapre_gli_ordini(self):
        viaggio = self.viaggio_pianificato()
        ordini = {r["ordine_id"] for t in viaggio["tappe"] for r in t["righe"]}
        annullato = self.esecuzione.annulla_viaggio(viaggio["id"], "Mezzo non disponibile")
        self.assertEqual(annullato["stato"], "ANNULLATO")
        for ordine_id in ordini:
            stato = self.db.query_uno("SELECT stato FROM ordini WHERE id = ?", (ordine_id,))["stato"]
            self.assertEqual(stato, "DA_PIANIFICARE")

    def test_il_diario_registra_ogni_passaggio(self):
        viaggio = self.viaggio_pianificato()
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        tipi = [e["tipo"] for e in self.esecuzione.dettaglio_viaggio(viaggio["id"])["eventi"]]
        self.assertEqual(tipi[:3], ["CREAZIONE", "ASSEGNAZIONE", "PARTENZA"])


class TestOtif(BaseEsecuzione):
    def test_consegna_nei_tempi_e_completa_e_otif(self):
        viaggio = self.viaggio_pianificato()
        # Si consegna nella data richiesta dagli ordini, a meta' mattina.
        ordini = {
            r["ordine_id"]: self.db.query_uno(
                "SELECT data_richiesta FROM ordini WHERE id = ?", (r["ordine_id"],)
            )["data_richiesta"]
            for t in viaggio["tappe"]
            for r in t["righe"]
        }
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        for tappa in viaggio["tappe"]:
            data = ordini[tappa["righe"][0]["ordine_id"]]
            self.esecuzione.registra_esito_tappa(tappa["id"], data, 10.0)
        self.esecuzione.chiudi_viaggio(viaggio["id"])

        riferimenti = {
            r["riferimento"] for t in viaggio["tappe"] for r in t["righe"]
        }
        esiti = [e for e in self.otif.dettaglio_ordini() if e["riferimento"] in riferimenti]
        self.assertTrue(esiti)
        for esito in esiti:
            self.assertTrue(esito["on_time"], esito)
            self.assertTrue(esito["in_full"], esito)
            self.assertTrue(esito["otif"], esito)
            self.assertEqual(esito["ritardo_minuti"], 0.0)

    def test_consegna_oltre_la_chiusura_non_e_puntuale(self):
        viaggio = self.viaggio_pianificato()
        tappa = viaggio["tappe"][0]
        ordine = self.db.query_uno(
            "SELECT riferimento, data_richiesta FROM ordini WHERE id = ?",
            (tappa["righe"][0]["ordine_id"],),
        )
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        self.esecuzione.registra_esito_tappa(
            tappa["id"], ordine["data_richiesta"], tappa["chiusura"] + 2.0, causale="TRAFFICO"
        )
        esito = next(
            e for e in self.otif.dettaglio_ordini() if e["riferimento"] == ordine["riferimento"]
        )
        self.assertFalse(esito["on_time"])
        self.assertTrue(esito["in_full"])
        self.assertFalse(esito["otif"])
        self.assertGreater(esito["ritardo_minuti"], 60)
        self.assertEqual(esito["causale"], "TRAFFICO")

    def test_consegna_incompleta_non_e_in_full(self):
        viaggio = self.viaggio_pianificato()
        tappa = viaggio["tappe"][0]
        riga = tappa["righe"][0]
        ordine = self.db.query_uno(
            "SELECT riferimento, data_richiesta FROM ordini WHERE id = ?", (riga["ordine_id"],)
        )
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        self.esecuzione.registra_esito_tappa(
            tappa["id"], ordine["data_richiesta"], 9.0,
            {riga["id"]: riga["quantita_richiesta"] * 0.4}, causale="MERCE_MANCANTE",
        )
        esito = next(
            e for e in self.otif.dettaglio_ordini() if e["riferimento"] == ordine["riferimento"]
        )
        self.assertTrue(esito["on_time"])
        self.assertFalse(esito["in_full"])
        self.assertFalse(esito["otif"])
        self.assertGreater(esito["quantita_mancante"], 0)

    def test_la_tolleranza_sul_ritardo_sposta_il_giudizio(self):
        viaggio = self.viaggio_pianificato()
        tappa = viaggio["tappe"][0]
        ordine = self.db.query_uno(
            "SELECT riferimento, data_richiesta FROM ordini WHERE id = ?",
            (tappa["righe"][0]["ordine_id"],),
        )
        self.esecuzione.assegna(viaggio["id"], vettore_id=1)
        self.esecuzione.registra_partenza(viaggio["id"])
        # Venti minuti oltre la chiusura del sito.
        self.esecuzione.registra_esito_tappa(
            tappa["id"], ordine["data_richiesta"], tappa["chiusura"] + 1 / 3
        )
        stretta = next(
            e for e in self.otif.dettaglio_ordini(tolleranza_minuti=0)
            if e["riferimento"] == ordine["riferimento"]
        )
        larga = next(
            e for e in self.otif.dettaglio_ordini(tolleranza_minuti=30)
            if e["riferimento"] == ordine["riferimento"]
        )
        self.assertFalse(stretta["on_time"])
        self.assertTrue(larga["on_time"])

    def test_il_ritardo_gia_previsto_dal_piano_e_attribuito_alla_pianificazione(self):
        # Viaggio su piu' giorni: le ultime tappe sono pianificate oltre la
        # data richiesta, quindi il ritardo non nasce dall'esecuzione.
        multigiorno = next(
            v for v in self.esecuzione.elenco_viaggi(stato="PIANIFICATO", limite=1000)
            if v["giorni_previsti"] > 1
        )
        viaggio = self.esecuzione.dettaglio_viaggio(multigiorno["id"])
        self.esegui_viaggio(viaggio)
        riferimenti = {r["riferimento"] for t in viaggio["tappe"] for r in t["righe"]}
        esiti = [e for e in self.otif.dettaglio_ordini() if e["riferimento"] in riferimenti]
        da_piano = [e for e in esiti if e["causale"] == self.esecuzione.CAUSALE_PIANO]
        self.assertTrue(da_piano, "Almeno una consegna doveva risultare gia' pianificata in ritardo")
        for esito in da_piano:
            self.assertFalse(esito["on_time"])
            self.assertGreater(esito["ritardo_da_piano_minuti"], 0)

    def test_cruscotto_coerente_con_il_dettaglio(self):
        cruscotto = self.otif.cruscotto_otif()
        esiti = self.otif.dettaglio_ordini()
        self.assertEqual(cruscotto["totali"]["ordini"], len(esiti))
        self.assertEqual(cruscotto["totali"]["otif"], sum(1 for e in esiti if e["otif"]))
        self.assertLessEqual(cruscotto["totali"]["otif_pct"], cruscotto["totali"]["on_time_pct"])
        self.assertLessEqual(cruscotto["totali"]["otif_pct"], cruscotto["totali"]["in_full_pct"])
        self.assertEqual(
            sum(m["ordini"] for m in cruscotto["mancati"]),
            cruscotto["totali"]["ordini"] - cruscotto["totali"]["otif"],
        )

    def test_consuntivo_costi_somma_i_viaggi_chiusi(self):
        viaggio = self.viaggio_pianificato()
        self.esegui_viaggio(viaggio)
        self.esecuzione.chiudi_viaggio(viaggio["id"], km_effettivi=500, costo_effettivo=900)
        consuntivo = self.otif.consuntivo_costi()
        chiusi = self.esecuzione.elenco_viaggi(stato="COMPLETATO", limite=1000)
        self.assertEqual(consuntivo["viaggi"], len(chiusi))
        self.assertAlmostEqual(
            consuntivo["totali"]["costo_effettivo"],
            round(sum(v["costo_effettivo"] for v in chiusi), 2),
            places=1,
        )


class TestSimulazione(BaseEsecuzione):
    def test_la_simulazione_produce_un_otif_plausibile(self):
        from app import simulazione

        importlib.reload(simulazione)
        esito = simulazione.simula_esecuzione(seed=3)
        self.assertGreater(esito["viaggi_eseguiti"], 0)
        self.assertEqual(
            self.esecuzione.elenco_viaggi(stato="PIANIFICATO", limite=1000), []
        )
        totali = self.otif.cruscotto_otif()["totali"]
        self.assertGreater(totali["otif_pct"], 50)
        self.assertLess(totali["otif_pct"], 100)
        self.assertGreaterEqual(totali["on_time_pct"], totali["otif_pct"])
        self.assertGreaterEqual(totali["in_full_pct"], totali["otif_pct"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
