"""Verifiche del motore di calcolo: geografia, costi, scorte, carichi, giri."""
from __future__ import annotations

import unittest

from app.core.consolidamento import (
    RigaCarico,
    Spedizione,
    consolida,
    pallet_necessari,
    scegli_veicolo,
)
from app.core.costi import (
    PROFILI_VEICOLO,
    TariffaVettore,
    co2_kg,
    confronta_make_or_buy,
    costo_flotta_propria,
    costo_vettore,
    peso_tassabile_kg,
)
from app.core.geo import (
    MatriceDistanze,
    Punto,
    collegamento_marittimo,
    distanza_stradale_km,
    haversine_km,
    isola,
    tempo_percorrenza_ore,
)
from app.core.riordino import (
    Squilibrio,
    calcola_parametri,
    lotto_economico,
    piano_bilanciamento,
    scorta_sicurezza,
    z_score,
)
from app.core.vrp import (
    MAX_ORE_GUIDA_GIORNO,
    Fermata,
    ottimizza_giri,
    simula_giro,
)

MILANO = Punto(1, 45.4642, 9.1900)
ROMA = Punto(2, 41.9028, 12.4964)
NAPOLI = Punto(3, 40.8518, 14.2681)
CATANIA = Punto(4, 37.5079, 15.0830)
CAGLIARI = Punto(5, 39.2238, 9.1217)
BOLOGNA = Punto(6, 44.4949, 11.3426)


class TestGeografia(unittest.TestCase):
    def test_haversine_simmetrica_e_nulla_su_se_stessa(self):
        self.assertAlmostEqual(haversine_km(45.0, 9.0, 45.0, 9.0), 0.0)
        self.assertAlmostEqual(
            haversine_km(45.0, 9.0, 41.0, 12.0), haversine_km(41.0, 12.0, 45.0, 9.0)
        )

    def test_distanze_stradali_entro_il_10_per_cento_del_reale(self):
        riferimenti = [
            (MILANO, ROMA, 575),
            (ROMA, NAPOLI, 225),
            (MILANO, BOLOGNA, 210),
        ]
        for a, b, reale in riferimenti:
            with self.subTest(tratta=f"{a.id}-{b.id}"):
                stimata = distanza_stradale_km(a, b)
                self.assertLess(abs(stimata - reale) / reale, 0.10)

    def test_tempo_percorrenza_cresce_con_la_distanza(self):
        self.assertLess(tempo_percorrenza_ore(20), tempo_percorrenza_ore(200))
        self.assertGreater(tempo_percorrenza_ore(600), 7.0)

    def test_riconoscimento_isole(self):
        self.assertEqual(isola(CATANIA.lat, CATANIA.lon), "SICILIA")
        self.assertEqual(isola(CAGLIARI.lat, CAGLIARI.lon), "SARDEGNA")
        self.assertIsNone(isola(MILANO.lat, MILANO.lon))

    def test_traghetto_richiesto_solo_verso_le_isole(self):
        self.assertIsNone(collegamento_marittimo(MILANO, ROMA))
        self.assertIsNotNone(collegamento_marittimo(MILANO, CATANIA))
        sardegna = collegamento_marittimo(ROMA, CAGLIARI)
        self.assertIsNotNone(sardegna)
        self.assertIn("Civitavecchia", sardegna["tratta"])
        self.assertGreater(sardegna["costo_eur"], 300)

    def test_collegamento_interno_alla_stessa_isola_e_stradale(self):
        palermo = Punto(9, 38.1157, 13.3615)
        self.assertIsNone(collegamento_marittimo(CATANIA, palermo))

    def test_matrice_espone_ore_di_guida_al_netto_della_traversata(self):
        matrice = MatriceDistanze([MILANO, CAGLIARI])
        self.assertLess(matrice.ore_guida(1, 5), matrice.ore(1, 5))
        self.assertIsNotNone(matrice.traghetto(1, 5))


class TestCosti(unittest.TestCase):
    def test_costo_variabile_km_cresce_con_la_portata(self):
        furgone = PROFILI_VEICOLO["FURGONE"].costo_variabile_km
        bilico = PROFILI_VEICOLO["BILICO"].costo_variabile_km
        self.assertLess(furgone, bilico)

    def test_scomposizione_costo_somma_al_totale(self):
        dettaglio = costo_flotta_propria(PROFILI_VEICOLO["BILICO"], 500, 7.5, 1.0)
        somma = (
            dettaglio.carburante
            + dettaglio.pedaggi
            + dettaglio.manutenzione
            + dettaglio.personale
            + dettaglio.costi_fissi
        )
        self.assertAlmostEqual(somma, dettaglio.totale, places=1)

    def test_peso_tassabile_usa_il_volumetrico_quando_superiore(self):
        self.assertEqual(peso_tassabile_kg(100, 2.0), 500.0)
        self.assertEqual(peso_tassabile_kg(900, 2.0), 900.0)

    def test_listino_groupage_decresce_per_quintale(self):
        piccola = costo_vettore(100, 0.2, 300).totale / 1.0
        grande = costo_vettore(4000, 8.0, 300).totale / 40.0
        self.assertLess(grande, piccola)

    def test_minimo_fatturabile_applicato(self):
        tariffa = TariffaVettore(nome="Prova", minimo_fatturabile=40.0, supplemento_carburante_pct=0.0)
        self.assertAlmostEqual(costo_vettore(1, 0.001, 20, tariffa).totale, 40.0)

    def test_supplemento_isole(self):
        continentale = costo_vettore(2000, 5, 700).totale
        isolano = costo_vettore(2000, 5, 700, isole=True).totale
        self.assertGreater(isolano, continentale)

    def test_make_or_buy_sceglie_il_meno_caro(self):
        esito = confronta_make_or_buy(PROFILI_VEICOLO["BILICO"], 600, 9, 1, 500, 1.0)
        atteso = min(esito["conto_proprio"]["totale"], esito["conto_terzi"]["totale"])
        scelto = esito["conto_proprio" if esito["scelta_consigliata"] == "PROPRIO" else "conto_terzi"]
        self.assertAlmostEqual(scelto["totale"], atteso)

    def test_co2_proporzionale_ai_km(self):
        profilo = PROFILI_VEICOLO["MOTRICE_180"]
        self.assertAlmostEqual(co2_kg(profilo, 200), co2_kg(profilo, 100) * 2, places=1)


class TestScorte(unittest.TestCase):
    def test_z_score_monotono(self):
        self.assertLess(z_score(0.90), z_score(0.95))
        self.assertLess(z_score(0.95), z_score(0.99))

    def test_scorta_sicurezza_cresce_con_variabilita_e_servizio(self):
        base = scorta_sicurezza(50, 10, 4, 0.5, 0.95)
        piu_variabile = scorta_sicurezza(50, 20, 4, 0.5, 0.95)
        piu_servizio = scorta_sicurezza(50, 10, 4, 0.5, 0.99)
        self.assertGreater(piu_variabile, base)
        self.assertGreater(piu_servizio, base)

    def test_scorta_sicurezza_nulla_senza_variabilita(self):
        self.assertAlmostEqual(scorta_sicurezza(50, 0, 4, 0, 0.95), 0.0)

    def test_lotto_economico_formula_di_wilson(self):
        # EOQ = sqrt(2 * 10000 * 50 / 2) = 707,1
        self.assertAlmostEqual(lotto_economico(10000, 50, 2), 707.1, places=1)
        self.assertEqual(lotto_economico(0, 50, 2), 0.0)

    def test_punto_riordino_copre_il_consumo_di_lead_time(self):
        parametri = calcola_parametri(1, 1, 40, 0, 5, 0, 0.95, 100)
        self.assertAlmostEqual(parametri.punto_riordino, 200.0)
        self.assertAlmostEqual(parametri.copertura_giorni, 2.5)


class TestBilanciamento(unittest.TestCase):
    def setUp(self):
        self.matrice = MatriceDistanze([MILANO, BOLOGNA, ROMA])

    def test_il_fabbisogno_e_coperto_dalla_origine_piu_vicina(self):
        squilibri = [
            Squilibrio(1, 10, giacenza=900, punto_riordino=100, scorta_massima=1000),
            Squilibrio(2, 10, giacenza=800, punto_riordino=100, scorta_massima=1000),
            Squilibrio(6, 10, giacenza=10, punto_riordino=200, scorta_massima=800),
        ]
        proposte = piano_bilanciamento(squilibri, self.matrice)
        self.assertEqual(len(proposte), 1)
        # Bologna e' piu' vicina a Milano che a Roma.
        self.assertEqual(proposte[0].origine_id, 1)
        self.assertEqual(proposte[0].destino_id, 6)
        self.assertAlmostEqual(proposte[0].quantita, 190.0)

    def test_senza_eccedenze_si_ricorre_alla_produzione(self):
        squilibri = [
            Squilibrio(1, 10, giacenza=50, punto_riordino=100, scorta_massima=500),
            Squilibrio(2, 10, giacenza=50, punto_riordino=100, scorta_massima=500),
        ]
        proposte = piano_bilanciamento(squilibri, self.matrice)
        self.assertTrue(all(p.origine_id == 0 for p in proposte))

    def test_nessuna_proposta_se_la_rete_e_in_equilibrio(self):
        squilibri = [Squilibrio(1, 10, giacenza=500, punto_riordino=100, scorta_massima=900)]
        self.assertEqual(piano_bilanciamento(squilibri, self.matrice), [])

    def test_il_limite_di_distanza_blocca_i_trasferimenti_lunghi(self):
        squilibri = [
            Squilibrio(1, 10, giacenza=900, punto_riordino=100, scorta_massima=1000),
            Squilibrio(2, 10, giacenza=0, punto_riordino=300, scorta_massima=900),
        ]
        proposte = piano_bilanciamento(squilibri, self.matrice, km_massimi=100)
        self.assertTrue(all(p.origine_id == 0 for p in proposte))


class TestConsolidamento(unittest.TestCase):
    def test_pallet_merce_non_sovrapponibile_occupa_posto_intero(self):
        self.assertEqual(pallet_necessari(100, 100, sovrapponibile=False), 1.0)
        self.assertEqual(pallet_necessari(100, 100, sovrapponibile=True), 0.5)
        self.assertEqual(pallet_necessari(101, 100, sovrapponibile=False), 2.0)

    def test_scelta_del_mezzo_piu_piccolo_sufficiente(self):
        self.assertEqual(scegli_veicolo(800, 5, 3).codice, "FURGONE")
        self.assertEqual(scegli_veicolo(20000, 80, 30).codice, "BILICO")

    def test_merce_adr_non_viene_mescolata(self):
        ordinaria = Spedizione("A", 1, 9, "2026-09-01", righe=[RigaCarico(1, 1, 10, 100, 1, 1)])
        pericolosa = Spedizione("B", 1, 9, "2026-09-01", righe=[RigaCarico(2, 2, 10, 100, 1, 1, adr=True)])
        carichi = consolida([ordinaria, pericolosa])
        self.assertEqual(len(carichi), 2)

    def test_le_spedizioni_compatibili_finiscono_nello_stesso_carico(self):
        spedizioni = [
            Spedizione(f"S{i}", 1, 9 + i, "2026-09-01", righe=[RigaCarico(i, 1, 10, 200, 1.0, 2)])
            for i in range(4)
        ]
        carichi = consolida(spedizioni)
        self.assertEqual(len(carichi), 1)
        self.assertEqual(carichi[0].pallet, 8)
        self.assertLessEqual(carichi[0].saturazione()["saturazione_pct"], 100.0)


class TestGiri(unittest.TestCase):
    def setUp(self):
        # Deposito e quattro clienti nel raggio lombardo.
        punti = [
            Punto(0, 45.50, 9.33),
            Punto(1, 45.70, 9.68),
            Punto(2, 45.44, 10.99),
            Punto(3, 45.16, 10.79),
            Punto(4, 45.07, 7.69),
        ]
        self.matrice = MatriceDistanze(punti)
        self.fermate = [
            Fermata(f"F{i}", i, 800, 3.0, 2, 8.0, 18.0) for i in range(1, 5)
        ]

    def test_il_consolidamento_riduce_i_km_rispetto_ai_viaggi_dedicati(self):
        giri = ottimizza_giri(0, self.fermate, self.matrice)
        km_ottimizzati = sum(g.km for g in giri)
        km_dedicati = sum(self.matrice.km(0, f.sito_id) * 2 for f in self.fermate)
        self.assertLess(km_ottimizzati, km_dedicati)

    def test_ogni_fermata_e_servita_una_sola_volta(self):
        giri = ottimizza_giri(0, self.fermate, self.matrice)
        serviti = [f.sito_id for g in giri for f in g.fermate]
        self.assertCountEqual(serviti, [f.sito_id for f in self.fermate])

    def test_la_capacita_del_mezzo_non_viene_superata(self):
        profilo = PROFILI_VEICOLO["FURGONE"]
        giri = ottimizza_giri(0, self.fermate, self.matrice, profilo=profilo)
        for giro in giri:
            self.assertLessEqual(giro.peso_kg, profilo.portata_kg)
            self.assertLessEqual(giro.pallet, profilo.posti_pallet)

    def test_le_finestre_orarie_sono_rispettate(self):
        giri = ottimizza_giri(0, self.fermate, self.matrice)
        for giro in giri:
            for fermata, tappa in zip(giro.fermate, giro.cronoprogramma):
                self.assertGreaterEqual(tappa["arrivo"], fermata.apertura - 1e-6)
                self.assertLessEqual(tappa["arrivo"], fermata.chiusura + 1e-6)

    def test_la_guida_giornaliera_resta_nel_limite_di_legge(self):
        simulazione = simula_giro(0, self.fermate, self.matrice)
        giorni = simulazione["giorni_impegno"]
        self.assertLessEqual(simulazione["ore_guida"] / giorni, MAX_ORE_GUIDA_GIORNO + 1e-6)

    def test_le_lunghe_percorrenze_diventano_viaggi_su_piu_giorni(self):
        matrice = MatriceDistanze([Punto(0, 45.50, 9.33), CATANIA])
        simulazione = simula_giro(0, [Fermata("F", 4, 500, 2, 2, 8.0, 17.0)], matrice)
        self.assertGreater(simulazione["giorni_impegno"], 1)
        self.assertEqual(simulazione["violazioni"], [])
        self.assertGreater(simulazione["costo_traghetti"], 0)

    def test_il_costo_del_giro_e_coerente_con_i_km(self):
        giri = ottimizza_giri(0, self.fermate, self.matrice)
        for giro in giri:
            self.assertGreater(giro.costo.totale, 0)
            self.assertGreater(giro.km, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
