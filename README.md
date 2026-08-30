# LogisticMaster

Piattaforma per l'ottimizzazione dei processi e dei flussi logistici e di
trasporto di aziende manifatturiere con **piu' stabilimenti produttivi e piu'
siti di stoccaggio**, calibrata sul mercato italiano (rete stradale, listini
groupage, normativa sui tempi di guida, collegamenti marittimi con le isole).

La piattaforma risponde alle domande operative di una direzione logistica:

* quali articoli stanno per andare in rottura di stock e in quale sito;
* quale sito puo' coprire il fabbisogno con le proprie eccedenze, invece di
  chiedere una nuova produzione;
* come raggruppare gli ordini della settimana in carichi e giri di consegna;
* quanto costa ogni giro, e se conviene farlo con la flotta aziendale o
  affidarlo a un vettore;
* quanto si risparmia rispetto a come si lavora oggi;
* che servizio si e' davvero dato al cliente, e per colpa di che cosa quando
  e' andata male.

---

## Avvio rapido

```bash
./run.sh                      # installa le dipendenze e avvia il server
# oppure
pip install -r requirements.txt
uvicorn app.main:app --reload
```

* Interfaccia operativa: <http://localhost:8000/>
* Documentazione API (OpenAPI/Swagger): <http://localhost:8000/api/docs>

Al primo avvio il database SQLite viene creato e popolato con uno scenario
dimostrativo: 3 stabilimenti, 4 depositi, 1 cross-dock, 26 clienti su tutta la
penisola, 12 articoli e circa 70 ordini da pianificare. Per ricaricarlo:

```bash
python -m app.seed          # da riga di comando
curl -X POST localhost:8000/api/admin/ricarica-demo
```

Test:

```bash
python -m unittest discover -s tests -v      # 87 test
```

## Demo statica

Per mostrare la piattaforma senza avviare il server (una presentazione, un
invio via mail) si genera una copia navigabile in un unico file HTML, con lo
scenario gia' calcolato dal motore e il simulatore make or buy funzionante in
pagina:

```bash
python demo/costruisci.py     # produce demo/logisticmaster-demo.html
```

---

## Moduli funzionali

### 1. Anagrafiche di rete
Stabilimenti, depositi, cross-dock, clienti e fornitori con coordinate,
capacita' in posti pallet, finestre orarie e baie di carico. Articoli con peso,
volume, pezzi per pallet, classe ABC, ADR, sovrapponibilita' e temperatura
controllata. Flotta aziendale e vettori convenzionati.

### 2. Analisi delle scorte (`app/core/riordino.py`)
Per ogni coppia sito/articolo calcola:

* **scorta di sicurezza** con variabilita' congiunta di domanda e lead time
  `SS = z · √(LT·σ²domanda + domanda²·σ²LT)`;
* **punto di riordino** `ROP = domanda · LT + SS`;
* **lotto economico** con la formula di Wilson;
* **copertura residua** in giorni e classificazione dell'urgenza
  (rottura / critica / alta / normale) rispetto al lead time.

### 3. Riequilibrio inter-sito
Prima di generare una richiesta a produzione, i fabbisogni vengono coperti con
le eccedenze degli altri siti: per ogni fabbisogno si attinge dalle origini piu'
vicine che restano sopra il proprio punto di riordino, entro una distanza
massima configurabile. Quello che la rete non copre diventa una richiesta
esplicita a produzione o fornitore.

### 4. Consolidamento dei carichi (`app/core/consolidamento.py`)
Le righe d'ordine diventano pallet (con gestione della merce non
sovrapponibile), le spedizioni compatibili vengono aggregate con logica
*first-fit decreasing* e a ogni carico viene assegnato il mezzo piu' piccolo
sufficiente. Merce ADR e a temperatura controllata non viene mai mescolata con
quella ordinaria. Per ogni carico si calcola la saturazione su peso, volume e
posti pallet, indicando quale dei tre e' il vincolo attivo.

### 5. Ottimizzazione dei giri (`app/core/vrp.py`)
VRP con capacita' e finestre orarie risolto in due fasi:

1. **Clarke & Wright** (savings paralleli): fonde i giri che fanno risparmiare
   piu' chilometri, verificando capacita', finestre orarie e ammissibilita';
2. **2-opt** vincolato: riordina le fermate finche' trova miglioramenti che non
   violano i vincoli.

La simulazione del giro rispetta il **Reg. CE 561/2006**: 9 ore di guida
giornaliera, pausa di 45 minuti ogni 4,5 ore di guida continuata, 13 ore di
impegno massimo. I viaggi a lunga percorrenza non vengono scartati ma
**pianificati su piu' giorni**, con riposo giornaliero e ripresa il mattino
successivo; il cronoprogramma riporta giorno e orario di ogni fermata.

### 6. Costing e make or buy (`app/core/costi.py`)
* **Conto proprio**: carburante (consumo per profilo di mezzo), pedaggi
  autostradali, manutenzione e pneumatici, costo del personale viaggiante,
  quota dei costi fissi giornalieri, traghetti.
* **Conto terzi**: listino groupage nazionale a scaglioni di peso con
  coefficiente per fascia di percorrenza, peso volumetrico (250 kg/m³), minimo
  di fatturazione, fuel surcharge, maggiorazione per Sicilia e Sardegna.
* Il confronto viene fatto **su ogni singolo giro** e la scelta consigliata
  entra nel costo ottimizzato di piano.

### 7. Collegamenti marittimi
Le relazioni con Sicilia e Sardegna passano dai porti reali (Genova, Livorno,
Civitavecchia, Napoli, Villa San Giovanni verso Porto Torres, Olbia, Cagliari,
Messina). La piattaforma calcola la percorrenza stradale fino al porto, il
tempo e il costo della traversata, e considera le ore di traghetto **tempo di
riposo e non di guida** ai fini della normativa.

### 8. Esecuzione dei viaggi (`app/core/esecuzione.py`)
Ogni giro del piano salvato diventa un **viaggio** con le sue tappe e le
righe da consegnare. Il viaggio attraversa una macchina a stati controllata
(pianificato → assegnato → in corso → completato, con annullamento possibile
finche' non e' concluso): non si parte senza assegnazione, non si registra un
esito prima della partenza, non si chiude con tappe ancora aperte e lo stesso
mezzo non puo' essere impegnato due volte in giornata.

Su ogni tappa si registrano orario di arrivo, quantita' effettivamente
scaricate e causale dell'eventuale disservizio; gli ordini serviti per intero
passano a consegnato, quelli parziali restano aperti. Ogni passaggio finisce
nel diario del viaggio, che resta la traccia di cosa e' successo e quando.
La chiusura raccoglie percorrenza e costo effettivi.

### 9. OTIF a consuntivo (`app/core/otif.py`)
Il livello di servizio si misura **per ordine**, perche' e' il cliente a
percepirlo:

* **On Time** - consegna entro la finestra concordata (data richiesta e
  orario di chiusura del sito destinatario), con franchigia in minuti
  configurabile e possibilita' di rifiutare le consegne anticipate;
* **In Full** - tutte le righe consegnate per intero, entro l'eventuale
  tolleranza percentuale;
* **OTIF** - entrambe le condizioni.

Il cruscotto scompone il mancato servizio in *solo ritardo*, *solo
incompleto* ed *entrambi*, lo aggrega per cliente, per modalita' di
esecuzione e per causale, e distingue i ritardi imputabili all'esecuzione da
quelli **gia' previsti dal piano** (tipicamente lunghe percorrenze servite in
piu' giorni): si correggono pianificando diversamente, non spingendo sugli
autisti. A fianco, il consuntivo economico confronta costo e percorrenza
pianificati con quelli effettivi, viaggio per viaggio.

Per valutare il cruscotto prima dell'innesto sul gestionale,
`app/simulazione.py` genera esiti verosimili (`POST /api/admin/simula-esecuzione`).

### 10. Cruscotto KPI
Valore delle giacenze per sito, combinazioni sotto punto di riordino, rischio
rottura, copertura media, e per ogni piano: km totali, costo totale e
ottimizzato, costo per km / per pallet / per tonnellata-chilometro,
saturazione media, giri sottosaturi candidati al groupage, CO₂ totale e per
tonnellata-chilometro, confronto con lo scenario senza ottimizzazione con
scomposizione del risparmio fra consolidamento e make or buy.

---

## Architettura

```
app/
  main.py                 applicazione FastAPI, avvio e file statici
  db.py                   schema SQLite e accesso ai dati
  models.py               schemi di validazione (Pydantic v2)
  seed.py                 scenario dimostrativo italiano
  simulazione.py          generatore di consuntivi verosimili per la demo
  api/
    anagrafiche.py        siti, articoli, giacenze, flotta, ordini
    pianificazione.py     scorte, trasferimenti, piani, simulazioni
    esecuzione.py         viaggi, esiti delle tappe, OTIF, consuntivo
    kpi.py                cruscotto direzionale e serie storica
  core/
    geo.py                distanze stradali, tempi, traghetti
    costi.py              modello di costo conto proprio / conto terzi
    riordino.py           scorte di sicurezza e riequilibrio di rete
    consolidamento.py     pallet, carichi, scelta del mezzo
    vrp.py                ottimizzazione dei giri e tempi di guida
    pianificazione.py     orchestrazione del piano e KPI
    esecuzione.py         viaggi, tappe, esiti di consegna
    otif.py               livello di servizio e scostamenti di costo
web/                      interfaccia operativa (HTML/CSS/JS, zero dipendenze)
tests/                    87 test su motore, esecuzione e API
```

Dipendenze: FastAPI, Uvicorn, Pydantic. Il database e' SQLite (nessun servizio
esterno), la matrice delle distanze e' calcolata in locale: la piattaforma
funziona anche senza connettivita'.

---

## API principali

| Metodo | Percorso | Descrizione |
|---|---|---|
| GET | `/api/siti` | Elenco siti, filtrabile per tipo |
| POST | `/api/siti` | Nuovo sito (coordinate validate sul territorio italiano) |
| GET | `/api/giacenze` | Giacenze per sito e articolo |
| GET | `/api/ordini` | Portafoglio ordini con peso e volume calcolati |
| POST | `/api/ordini` | Inserimento ordine con righe |
| GET | `/api/scorte/analisi` | Scorta di sicurezza, ROP, copertura, criticita' |
| GET | `/api/scorte/trasferimenti` | Proposte di riequilibrio inter-sito |
| POST | `/api/piani/genera` | Piano di trasporto ottimizzato con KPI |
| GET | `/api/piani/{id}` | Piano salvato |
| POST | `/api/simulazioni/make-or-buy` | Confronto conto proprio / conto terzi |
| GET | `/api/rete/matrice` | Matrice distanze e tempi fra siti interni |
| GET | `/api/kpi/cruscotto` | Indicatori di rete e magazzino |
| GET | `/api/viaggi` | Viaggi con stato, avanzamento e scostamenti |
| POST | `/api/viaggi/{id}/assegnazione` | Assegnazione a mezzo aziendale o vettore |
| POST | `/api/viaggi/{id}/partenza` | Registrazione della partenza |
| POST | `/api/tappe/{id}/esito` | Arrivo, quantita' consegnate, causale |
| POST | `/api/viaggi/{id}/chiusura` | Chiusura con km e costo effettivi |
| GET | `/api/kpi/otif` | OTIF a consuntivo con cause e scomposizioni |
| GET | `/api/kpi/consuntivo` | Costo pianificato contro costo effettivo |

---

## Parametri da tarare prima dell'uso in produzione

I valori di default sono di mercato, non aziendali. Vanno allineati ai dati
reali dell'impresa:

* `app/core/costi.py`: prezzo del gasolio, consumi, pedaggi, costo orario degli
  autisti, costi fissi dei mezzi, scaglioni e coefficienti del listino vettori,
  supplemento isole, tariffe dei traghetti;
* `app/core/geo.py`: fattore di tortuosita' della rete stradale e velocita'
  commerciali medie;
* `app/core/riordino.py`: costo di emissione ordine e tasso di mantenimento a
  scorta.

**Accuratezza delle distanze.** Le percorrenze sono stimate da coordinate e non
da un servizio di routing: su un campione di relazioni nazionali note l'errore
medio assoluto e' del 4-5%. Per la fatturazione al chilometro va integrato un
motore di routing reale; per la pianificazione e il confronto fra alternative
la stima e' adeguata.

---

## Sviluppi naturali successivi

* Integrazione con il gestionale (ERP) per ordini e giacenze in tempo reale.
* Routing reale (OSRM o servizio commerciale) al posto della stima geografica.
* Anagrafica tariffaria per vettore con listini caricati da file.
* Riconciliazione automatica fra costo pianificato e fattura del vettore.
* Acquisizione degli esiti di consegna da app mobile o EDI del vettore, al
  posto della registrazione manuale.
* Vincoli aggiuntivi: patenti e abilitazioni ADR degli autisti, prenotazione
  delle baie di carico, finestre di consegna della GDO.
