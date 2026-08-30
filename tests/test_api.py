"""Verifiche delle API su un database temporaneo popolato con lo scenario demo."""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cartella = tempfile.TemporaryDirectory()
        os.environ["LOGISTICMASTER_DB"] = os.path.join(cls.cartella.name, "prova.db")

        # I moduli vanno ricaricati perche' il percorso del DB e' letto all'import.
        from app import db

        importlib.reload(db)
        from app import seed

        importlib.reload(seed)
        seed.popola(seed=7)

        from fastapi.testclient import TestClient

        from app import main

        importlib.reload(main)
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()
        os.environ.pop("LOGISTICMASTER_DB", None)

    # ------------------------------------------------------------ anagrafiche
    def test_stato_operativo(self):
        dati = self.client.get("/api/stato").json()
        self.assertEqual(dati["stato"], "operativo")
        self.assertGreater(dati["conteggi"]["siti"], 0)

    def test_elenco_siti_e_filtro_per_tipo(self):
        tutti = self.client.get("/api/siti").json()
        stabilimenti = self.client.get("/api/siti?tipo=STABILIMENTO").json()
        self.assertGreater(len(tutti), len(stabilimenti))
        self.assertTrue(all(s["tipo"] == "STABILIMENTO" for s in stabilimenti))

    def test_dettaglio_sito_include_giacenze(self):
        dati = self.client.get("/api/siti/1").json()
        self.assertIn("giacenze", dati)
        self.assertTrue(dati["giacenze"])

    def test_creazione_sito_e_rifiuto_del_duplicato(self):
        nuovo = {
            "codice": "CL-PROVA",
            "nome": "Cliente di prova",
            "tipo": "CLIENTE",
            "comune": "Prato",
            "provincia": "PO",
            "lat": 43.88,
            "lon": 11.10,
        }
        creato = self.client.post("/api/siti", json=nuovo)
        self.assertEqual(creato.status_code, 201)
        self.assertEqual(self.client.post("/api/siti", json=nuovo).status_code, 409)

    def test_coordinate_fuori_dal_territorio_italiano_rifiutate(self):
        risposta = self.client.post(
            "/api/siti",
            json={
                "codice": "XX-1",
                "nome": "Estero",
                "tipo": "CLIENTE",
                "comune": "Parigi",
                "provincia": "XX",
                "lat": 48.85,
                "lon": 2.35,
            },
        )
        self.assertEqual(risposta.status_code, 422)

    def test_sito_inesistente_restituisce_404(self):
        self.assertEqual(self.client.get("/api/siti/99999").status_code, 404)

    def test_creazione_ordine_con_articolo_inesistente(self):
        risposta = self.client.post(
            "/api/ordini",
            json={
                "origine_id": 4,
                "destino_id": 9,
                "data_richiesta": "2026-09-20",
                "righe": [{"articolo_id": 99999, "quantita": 5}],
            },
        )
        self.assertEqual(risposta.status_code, 404)

    def test_creazione_ordine_valido(self):
        risposta = self.client.post(
            "/api/ordini",
            json={
                "origine_id": 4,
                "destino_id": 9,
                "data_richiesta": "2026-09-20",
                "righe": [{"articolo_id": 1, "quantita": 50}],
            },
        )
        self.assertEqual(risposta.status_code, 201)
        self.assertEqual(risposta.json()["stato"], "DA_PIANIFICARE")

    def test_aggiornamento_stato_ordine(self):
        ordine = self.client.get("/api/ordini").json()[0]
        risposta = self.client.patch(f"/api/ordini/{ordine['id']}/stato?stato=CONSEGNATO")
        self.assertEqual(risposta.json()["stato"], "CONSEGNATO")
        self.assertEqual(
            self.client.patch(f"/api/ordini/{ordine['id']}/stato?stato=INVENTATO").status_code, 422
        )

    # ------------------------------------------------------------ scorte
    def test_analisi_scorte_coerente(self):
        dati = self.client.get("/api/scorte/analisi").json()
        self.assertTrue(dati["righe"])
        for riga in dati["righe"]:
            self.assertGreaterEqual(riga["punto_riordino"], riga["scorta_sicurezza"])
            self.assertEqual(riga["sotto_riordino"], riga["disponibile"] < riga["punto_riordino"])

    def test_filtro_solo_critiche(self):
        critiche = self.client.get("/api/scorte/analisi?solo_critiche=true").json()
        self.assertTrue(all(r["sotto_riordino"] for r in critiche["righe"]))

    def test_proposte_trasferimento_partono_da_siti_diversi(self):
        dati = self.client.get("/api/scorte/trasferimenti").json()
        for proposta in dati["proposte"]:
            self.assertNotEqual(proposta["origine_id"], proposta["destino_id"])
            self.assertGreater(proposta["quantita"], 0)

    # ------------------------------------------------------------ piano
    def test_generazione_piano_e_kpi(self):
        piano = self.client.post("/api/piani/genera", json={}).json()
        kpi = piano["kpi"]
        self.assertGreater(kpi["giri"], 0)
        self.assertEqual(kpi["fermate"], sum(len(g["sequenza"]) for g in piano["giri"]))
        self.assertAlmostEqual(
            kpi["km_totali"], round(sum(g["km"] for g in piano["giri"]), 1), places=1
        )
        # Il consolidamento non puo' costare piu' dei viaggi dedicati.
        self.assertLessEqual(kpi["costo_ottimizzato_eur"], piano["scenario_base"]["costo_eur"])
        self.assertGreaterEqual(piano["confronto"]["km_risparmiati"], 0)

    def test_ogni_spedizione_compare_in_un_solo_giro(self):
        piano = self.client.post("/api/piani/genera", json={}).json()
        riferimenti = [
            r for g in piano["giri"] for f in g["fermate"] for r in f["spedizioni"]
        ]
        self.assertEqual(len(riferimenti), len(set(riferimenti)))
        self.assertEqual(len(riferimenti), piano["spedizioni"])

    def test_salvataggio_piano_marca_gli_ordini(self):
        piano = self.client.post(
            "/api/piani/genera", json={"salva": True, "descrizione": "Piano di prova"}
        ).json()
        self.assertIn("piano_id", piano)
        dettaglio = self.client.get(f"/api/piani/{piano['piano_id']}").json()
        self.assertEqual(dettaglio["descrizione"], "Piano di prova")
        self.assertFalse(self.client.get("/api/ordini?stato=DA_PIANIFICARE").json())

    def test_parametri_piano_non_validi(self):
        self.assertEqual(
            self.client.post("/api/piani/genera", json={"profilo_predefinito": "NAVE"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/piani/genera", json={"data_da": "2026-09-10", "data_a": "2026-09-01"}
            ).status_code,
            422,
        )

    def test_piano_inesistente(self):
        self.assertEqual(self.client.get("/api/piani/999999").status_code, 404)

    # ------------------------------------------------------------ simulazioni
    def test_make_or_buy_confronta_le_due_alternative(self):
        esito = self.client.post(
            "/api/simulazioni/make-or-buy",
            json={
                "origine_id": 4,
                "destino_id": 9,
                "peso_kg": 5000,
                "volume_m3": 20,
                "pallet": 12,
            },
        ).json()
        self.assertIn(esito["scelta_consigliata"], ("PROPRIO", "TERZI"))
        self.assertGreater(esito["km_totali"], 0)
        self.assertGreater(esito["conto_terzi"]["totale"], 0)

    def test_make_or_buy_verso_isola_include_il_traghetto(self):
        cagliari = self.client.get("/api/siti?tipo=CLIENTE").json()
        sardegna = next(s for s in cagliari if s["provincia"] == "CA")
        esito = self.client.post(
            "/api/simulazioni/make-or-buy",
            json={
                "origine_id": 4,
                "destino_id": sardegna["id"],
                "peso_kg": 3000,
                "volume_m3": 12,
                "pallet": 6,
            },
        ).json()
        self.assertIsNotNone(esito["traghetto"])
        self.assertGreater(esito["conto_proprio"]["traghetti"], 0)

    def test_matrice_di_rete_simmetrica_con_diagonale_nulla(self):
        matrice = self.client.get("/api/rete/matrice").json()
        km = matrice["km"]
        for i, riga in enumerate(km):
            self.assertEqual(riga[i], 0.0)
            for j, valore in enumerate(riga):
                self.assertAlmostEqual(valore, km[j][i], places=2)

    # ------------------------------------------------------------ kpi
    def test_cruscotto_completo(self):
        dati = self.client.get("/api/kpi/cruscotto").json()
        self.assertIn("STABILIMENTO", dati["rete"])
        self.assertGreater(dati["magazzino"]["valore_giacenze_eur"], 0)
        self.assertTrue(dati["per_sito"])

    def test_interfaccia_e_documentazione_disponibili(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
