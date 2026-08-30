/* LogisticMaster - interfaccia operativa (nessuna dipendenza esterna). */
'use strict';

const stato = { siti: [], profili: [], piano: null };

/* ----------------------------------------------------------- utilita' */
const euro = (v) => (v ?? 0).toLocaleString('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
const euroPreciso = (v) => (v ?? 0).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' });
const numero = (v, d = 0) => (v ?? 0).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d });
const ora = (v) => {
  if (v === null || v === undefined) return '-';
  const h = Math.floor(v);
  const m = Math.round((v - h) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
};

async function api(percorso, opzioni = {}) {
  const risposta = await fetch(percorso, {
    headers: { 'Content-Type': 'application/json' },
    ...opzioni,
  });
  if (!risposta.ok) {
    const dettaglio = await risposta.json().catch(() => ({}));
    throw new Error(dettaglio.detail || `Errore ${risposta.status}`);
  }
  return risposta.json();
}

function tabella(elemento, colonne, righe, opzioni = {}) {
  const intestazione = colonne
    .map((c) => `<th class="${c.numero ? 'numero' : ''}">${c.titolo}</th>`)
    .join('');
  const corpo = righe
    .map((r, i) => {
      const celle = colonne
        .map((c) => `<td class="${c.numero ? 'numero' : ''}">${c.valore(r)}</td>`)
        .join('');
      return `<tr data-indice="${i}" class="${opzioni.selezionabile ? 'selezionabile' : ''}">${celle}</tr>`;
    })
    .join('');
  elemento.innerHTML = `<thead><tr>${intestazione}</tr></thead><tbody>${corpo || `<tr><td colspan="${colonne.length}" class="vuoto">Nessun dato</td></tr>`}</tbody>`;
  if (opzioni.alClick) {
    elemento.querySelectorAll('tbody tr[data-indice]').forEach((tr) => {
      tr.addEventListener('click', () => {
        elemento.querySelectorAll('tr').forEach((x) => x.classList.remove('selezionata'));
        tr.classList.add('selezionata');
        opzioni.alClick(righe[Number(tr.dataset.indice)]);
      });
    });
  }
}

function schedaKpi(etichetta, valore, nota = '', classe = '') {
  return `<div class="kpi ${classe}">
    <div class="etichetta">${etichetta}</div>
    <div class="valore">${valore}</div>
    ${nota ? `<div class="nota-kpi">${nota}</div>` : ''}
  </div>`;
}

/* --------------------------------------------------------- navigazione */
document.getElementById('navigazione').addEventListener('click', (evento) => {
  const bottone = evento.target.closest('.voce');
  if (!bottone) return;
  document.querySelectorAll('.voce').forEach((v) => v.classList.remove('attiva'));
  document.querySelectorAll('.sezione').forEach((s) => s.classList.remove('attiva'));
  bottone.classList.add('attiva');
  document.getElementById(`sezione-${bottone.dataset.sezione}`).classList.add('attiva');
  caricaSezione(bottone.dataset.sezione);
});

const caricate = new Set();
function caricaSezione(nome) {
  const azioni = {
    cruscotto: caricaCruscotto,
    rete: caricaRete,
    scorte: caricaScorte,
    trasferimenti: caricaTrasferimenti,
    ordini: caricaOrdini,
    piano: () => {},
    simulatore: () => {},
  };
  if (!caricate.has(nome)) {
    caricate.add(nome);
    (azioni[nome] || (() => {}))();
  }
}

/* ----------------------------------------------------------- cruscotto */
async function caricaCruscotto() {
  const dati = await api('/api/kpi/cruscotto');
  const rete = dati.rete || {};
  const magazzino = dati.magazzino;
  document.getElementById('kpi-cruscotto').innerHTML = [
    schedaKpi('Stabilimenti', numero(rete.STABILIMENTO || 0), 'unità produttive'),
    schedaKpi('Depositi e cross-dock', numero((rete.DEPOSITO || 0) + (rete.CROSSDOCK || 0)), 'siti di stoccaggio'),
    schedaKpi('Clienti serviti', numero(rete.CLIENTE || 0), 'punti di consegna'),
    schedaKpi('Valore giacenze', euro(magazzino.valore_giacenze_eur), 'capitale immobilizzato'),
    schedaKpi('Sotto punto di riordino', numero(magazzino.sotto_punto_riordino),
      `su ${numero(magazzino.coppie_sito_articolo)} combinazioni`,
      magazzino.sotto_punto_riordino > 0 ? 'attenzione' : 'positivo'),
    schedaKpi('Rischio rottura', numero(magazzino.rischio_rottura), 'copertura < lead time',
      magazzino.rischio_rottura > 0 ? 'critico' : 'positivo'),
    schedaKpi('Copertura media', `${numero(magazzino.copertura_media_giorni, 1)} gg`, 'giorni di stock'),
    schedaKpi('Ordini da pianificare', numero((dati.ordini || {}).DA_PIANIFICARE || 0), 'in portafoglio'),
  ].join('');

  const massimo = Math.max(...dati.per_sito.map((s) => s.valore_giacenze_eur), 1);
  document.getElementById('grafico-siti').innerHTML = dati.per_sito
    .map((s) => `<div class="barra-riga">
        <span>${s.sito}</span>
        <span class="barra"><span style="width:${(s.valore_giacenze_eur / massimo) * 100}%"></span></span>
        <span class="numero">${euro(s.valore_giacenze_eur)}</span>
      </div>`)
    .join('');

  tabella(document.getElementById('tabella-criticita'), [
    { titolo: 'Sito', valore: (r) => r.sito },
    { titolo: 'Articolo', valore: (r) => `${r.articolo}<br><small>${r.descrizione}</small>` },
    { titolo: 'Copertura', numero: true, valore: (r) => `${numero(r.copertura_giorni, 1)} gg` },
    { titolo: 'Lead time', numero: true, valore: (r) => `${numero(r.lead_time_giorni, 1)} gg` },
    { titolo: 'Disponibile', numero: true, valore: (r) => numero(r.disponibile) },
    { titolo: 'Punto riordino', numero: true, valore: (r) => numero(r.punto_riordino) },
  ], dati.criticita_top);

  const ultimo = dati.ultimo_piano || {};
  document.getElementById('kpi-ultimo-piano').innerHTML = Object.keys(ultimo).length
    ? [
        schedaKpi('Giri', numero(ultimo.giri)),
        schedaKpi('Km totali', numero(ultimo.km_totali)),
        schedaKpi('Costo', euro(ultimo.costo_totale_eur)),
        schedaKpi('Costo/km', euroPreciso(ultimo.costo_per_km)),
        schedaKpi('Saturazione', `${numero(ultimo.saturazione_media_pct, 1)}%`),
        schedaKpi('CO₂', `${numero(ultimo.co2_kg)} kg`),
      ].join('')
    : '<p class="vuoto">Nessun piano salvato: generane uno dalla sezione Piano di trasporto.</p>';
}

document.getElementById('aggiorna-cruscotto').addEventListener('click', caricaCruscotto);

/* ---------------------------------------------------------------- rete */
const COLORI_SITO = {
  STABILIMENTO: '#10395e',
  DEPOSITO: '#1c9c78',
  CROSSDOCK: '#b8791b',
  CLIENTE: '#8fa3b5',
  FORNITORE: '#7a5ea8',
};

/* Proiezione equirettangolare sul riquadro geografico italiano. */
function proiezione(lat, lon, larghezza = 460, altezza = 620) {
  const LAT_MIN = 36.4, LAT_MAX = 47.2, LON_MIN = 6.4, LON_MAX = 18.6;
  const x = ((lon - LON_MIN) / (LON_MAX - LON_MIN)) * (larghezza - 40) + 20;
  const y = altezza - 20 - ((lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * (altezza - 40);
  return [x, y];
}

/* Sagoma semplificata del territorio italiano: serve a dare riferimento
   visivo alla mappa, non ha pretese cartografiche. Punti [lat, lon]. */
const PROFILO_PENISOLA = [
  [45.80, 6.85], [46.45, 8.60], [46.60, 10.50], [46.90, 12.40], [46.50, 13.60],
  [45.80, 13.60], [45.55, 13.00], [45.50, 12.50], [44.90, 12.50], [44.20, 12.40],
  [43.90, 12.75], [43.60, 13.50], [42.90, 14.10], [42.40, 14.20], [41.90, 15.40],
  [41.90, 16.20], [41.40, 16.00], [41.10, 16.90], [40.50, 17.95], [40.10, 18.50],
  [39.80, 18.35], [40.00, 17.90], [40.40, 17.20], [40.00, 16.60], [39.40, 17.10],
  [38.90, 17.10], [38.50, 16.60], [37.92, 16.10], [38.10, 15.62], [38.60, 15.90],
  [39.40, 16.00], [40.00, 15.40], [40.60, 14.90], [40.80, 14.20], [41.20, 13.60],
  [41.40, 13.00], [41.80, 12.40], [42.40, 11.60], [43.00, 10.50], [43.60, 10.30],
  [44.20, 9.70], [44.30, 9.00], [44.00, 8.20], [43.80, 7.60], [44.70, 6.90],
  [45.10, 6.70],
];
const PROFILO_SICILIA = [
  [38.30, 15.62], [37.50, 15.10], [36.70, 15.10], [36.65, 14.30], [37.00, 13.20],
  [37.50, 12.50], [38.00, 12.40], [38.10, 13.40], [38.00, 14.50],
];
const PROFILO_SARDEGNA = [
  [41.25, 9.20], [40.90, 9.60], [40.50, 9.80], [39.90, 9.70], [39.20, 9.60],
  [38.90, 8.80], [39.20, 8.40], [39.90, 8.40], [40.60, 8.20], [40.90, 8.20],
];

function poligono(profilo) {
  const punti = profilo.map(([lat, lon]) => proiezione(lat, lon).map((v) => v.toFixed(1)).join(',')).join(' ');
  return `<polygon points="${punti}" fill="#dbe6ee" stroke="#b9cbd9" stroke-width="1"/>`;
}

function disegnaMappa(siti, giri = []) {
  const svg = document.getElementById('mappa');
  const linee = giri
    .flatMap((g) => {
      const sequenza = [g.deposito_id, ...g.sequenza, g.deposito_id];
      return sequenza.slice(1).map((destino, i) => {
        const a = siti.find((s) => s.id === sequenza[i]);
        const b = siti.find((s) => s.id === destino);
        if (!a || !b) return '';
        const [x1, y1] = proiezione(a.lat, a.lon);
        const [x2, y2] = proiezione(b.lat, b.lon);
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#1c5f96" stroke-width="1" opacity=".45"/>`;
      });
    })
    .join('');

  const punti = siti
    .map((s) => {
      const [x, y] = proiezione(s.lat, s.lon);
      const raggio = s.tipo === 'STABILIMENTO' ? 7 : s.tipo === 'DEPOSITO' ? 6 : s.tipo === 'CROSSDOCK' ? 5 : 3.5;
      // Le etichette dei siti interni si spostano a sinistra nella meta'
      // destra della mappa, per non uscire dal riquadro.
      const aDestra = x > 300;
      const etichetta = s.tipo === 'CLIENTE'
        ? ''
        : `<text x="${aDestra ? x - raggio - 3 : x + raggio + 3}" y="${y + 3.5}" font-size="9"
             text-anchor="${aDestra ? 'end' : 'start'}" fill="#12293f"
             stroke="#eaf1f6" stroke-width="2.5" paint-order="stroke">${s.codice}</text>`;
      return `<g><circle cx="${x}" cy="${y}" r="${raggio}" fill="${COLORI_SITO[s.tipo]}" stroke="#fff" stroke-width="1.2">
        <title>${s.nome} - ${s.comune} (${s.provincia})</title></circle>${etichetta}</g>`;
    })
    .join('');

  const terra = poligono(PROFILO_PENISOLA) + poligono(PROFILO_SICILIA) + poligono(PROFILO_SARDEGNA);
  svg.innerHTML = `<rect width="460" height="620" fill="#eaf1f6"/>${terra}${linee}${punti}`;
}

async function caricaRete() {
  stato.siti = await api('/api/siti');
  applicaFiltroSiti();
  const matrice = await api('/api/rete/matrice');
  const intestazione = ['<th>Da / A</th>', ...matrice.siti.map((s) => `<th class="numero">${s.codice}</th>`)].join('');
  const corpo = matrice.siti
    .map((s, i) => {
      const celle = matrice.km[i]
        .map((km, j) => `<td class="numero">${i === j ? '—' : numero(km)}</td>`)
        .join('');
      return `<tr><td><strong>${s.codice}</strong> ${s.nome}</td>${celle}</tr>`;
    })
    .join('');
  document.getElementById('tabella-matrice').innerHTML =
    `<thead><tr>${intestazione}</tr></thead><tbody>${corpo}</tbody>`;
}

function applicaFiltroSiti() {
  const filtro = document.getElementById('filtro-tipo-sito').value;
  const elenco = filtro ? stato.siti.filter((s) => s.tipo === filtro) : stato.siti;
  disegnaMappa(elenco);
  tabella(document.getElementById('tabella-siti'), [
    { titolo: 'Codice', valore: (s) => `<strong>${s.codice}</strong>` },
    { titolo: 'Nome', valore: (s) => s.nome },
    { titolo: 'Tipo', valore: (s) => s.tipo.toLowerCase() },
    { titolo: 'Comune', valore: (s) => `${s.comune} (${s.provincia})` },
    { titolo: 'Capacità', numero: true, valore: (s) => (s.capacita_pallet ? `${numero(s.capacita_pallet)} pl` : '-') },
    { titolo: 'Orari', valore: (s) => `${ora(s.apertura)}–${ora(s.chiusura)}` },
  ], elenco);
}

document.getElementById('filtro-tipo-sito').addEventListener('change', applicaFiltroSiti);

/* -------------------------------------------------------------- scorte */
async function caricaScorte() {
  const soloCritiche = document.getElementById('solo-critiche').checked;
  const dati = await api(`/api/scorte/analisi?solo_critiche=${soloCritiche}`);
  document.getElementById('kpi-scorte').innerHTML = [
    schedaKpi('Combinazioni analizzate', numero(dati.righe.length)),
    schedaKpi('Sotto punto di riordino', numero(dati.sotto_riordino), '', dati.sotto_riordino ? 'attenzione' : 'positivo'),
    schedaKpi('Valore giacenze', euro(dati.valore_giacenze)),
  ].join('');

  tabella(document.getElementById('tabella-scorte'), [
    { titolo: 'Sito', valore: (r) => `${r.sito_codice}<br><small>${r.sito_nome}</small>` },
    { titolo: 'Articolo', valore: (r) => `${r.articolo_codice} <small>(${r.classe_abc})</small><br><small>${r.articolo_descrizione}</small>` },
    { titolo: 'Disponibile', numero: true, valore: (r) => numero(r.disponibile) },
    { titolo: 'Domanda/gg', numero: true, valore: (r) => numero(r.domanda_media_giorno, 1) },
    { titolo: 'Copertura', numero: true, valore: (r) => `${numero(r.copertura_giorni, 1)} gg` },
    { titolo: 'Scorta sicurezza', numero: true, valore: (r) => numero(r.scorta_sicurezza) },
    { titolo: 'Punto riordino', numero: true, valore: (r) => numero(r.punto_riordino) },
    { titolo: 'Lotto riordino', numero: true, valore: (r) => numero(r.lotto_economico) },
    { titolo: 'Servizio', numero: true, valore: (r) => `${numero(r.livello_servizio * 100, 0)}%` },
    {
      titolo: 'Stato',
      valore: (r) => r.sotto_riordino
        ? '<span class="etichetta-stato stato-critica">da riordinare</span>'
        : '<span class="etichetta-stato stato-normale">ok</span>',
    },
  ], dati.righe);
}

document.getElementById('aggiorna-scorte').addEventListener('click', caricaScorte);
document.getElementById('solo-critiche').addEventListener('change', caricaScorte);

/* ------------------------------------------------------ trasferimenti */
async function caricaTrasferimenti() {
  const km = document.getElementById('km-massimi').value || 900;
  const dati = await api(`/api/scorte/trasferimenti?km_massimi=${km}`);
  document.getElementById('kpi-trasferimenti').innerHTML = [
    schedaKpi('Proposte totali', numero(dati.totale)),
    schedaKpi('Coperte dalla rete', numero(dati.da_rete), 'senza nuova produzione', 'positivo'),
    schedaKpi('A produzione/fornitore', numero(dati.da_produzione), 'rete senza eccedenze',
      dati.da_produzione ? 'attenzione' : 'positivo'),
    schedaKpi('Valore movimentato', euro(dati.valore_movimentato)),
  ].join('');

  tabella(document.getElementById('tabella-trasferimenti'), [
    {
      titolo: 'Urgenza',
      valore: (p) => `<span class="etichetta-stato stato-${p.urgenza.toLowerCase()}">${p.urgenza.toLowerCase()}</span>`,
    },
    { titolo: 'Articolo', valore: (p) => `${p.articolo_codice}<br><small>${p.articolo_descrizione}</small>` },
    { titolo: 'Da', valore: (p) => `${p.origine_codice}<br><small>${p.origine_nome}</small>` },
    { titolo: 'A', valore: (p) => `${p.destino_codice}<br><small>${p.destino_nome}</small>` },
    { titolo: 'Quantità', numero: true, valore: (p) => numero(p.quantita) },
    { titolo: 'Pallet', numero: true, valore: (p) => numero(p.pallet, 1) },
    { titolo: 'Peso', numero: true, valore: (p) => `${numero(p.peso_kg)} kg` },
    { titolo: 'Distanza', numero: true, valore: (p) => (p.km ? `${numero(p.km)} km` : '-') },
    { titolo: 'Valore', numero: true, valore: (p) => euro(p.valore) },
  ], dati.proposte);
}

document.getElementById('calcola-trasferimenti').addEventListener('click', caricaTrasferimenti);

/* -------------------------------------------------------------- ordini */
async function caricaOrdini() {
  const filtro = document.getElementById('filtro-stato-ordine').value;
  const ordini = await api(`/api/ordini${filtro ? `?stato=${filtro}` : ''}`);
  tabella(document.getElementById('tabella-ordini'), [
    { titolo: 'Riferimento', valore: (o) => `<strong>${o.riferimento}</strong>` },
    { titolo: 'Data', valore: (o) => o.data_richiesta },
    { titolo: 'Origine', valore: (o) => o.origine_nome || '-' },
    { titolo: 'Destinazione', valore: (o) => `${o.destino_nome}<br><small>${o.destino_comune} (${o.destino_provincia})</small>` },
    { titolo: 'Righe', numero: true, valore: (o) => numero(o.righe.length) },
    { titolo: 'Peso', numero: true, valore: (o) => `${numero(o.peso_kg)} kg` },
    { titolo: 'Volume', numero: true, valore: (o) => `${numero(o.volume_m3, 2)} m³` },
    { titolo: 'Priorità', numero: true, valore: (o) => o.priorita },
    { titolo: 'Stato', valore: (o) => `<span class="etichetta-stato stato-normale">${o.stato.toLowerCase().replace('_', ' ')}</span>` },
  ], ordini);
}

document.getElementById('aggiorna-ordini').addEventListener('click', caricaOrdini);
document.getElementById('filtro-stato-ordine').addEventListener('change', caricaOrdini);

/* --------------------------------------------------------------- piano */
async function generaPiano() {
  const bottone = document.getElementById('genera-piano');
  bottone.disabled = true;
  bottone.textContent = 'Ottimizzazione in corso…';
  try {
    const corpo = {
      data_da: document.getElementById('piano-data-da').value || null,
      data_a: document.getElementById('piano-data-a').value || null,
      ora_partenza: Number(document.getElementById('piano-ora').value),
      profilo_predefinito: document.getElementById('piano-profilo').value,
      sconto_vettore_pct: Number(document.getElementById('piano-sconto').value) / 100,
      salva: document.getElementById('piano-salva').checked,
      descrizione: 'Piano generato da interfaccia',
    };
    const piano = await api('/api/piani/genera', { method: 'POST', body: JSON.stringify(corpo) });
    stato.piano = piano;
    mostraPiano(piano);
  } catch (errore) {
    alert(`Errore nella generazione del piano: ${errore.message}`);
  } finally {
    bottone.disabled = false;
    bottone.textContent = 'Genera piano';
  }
}

function mostraPiano(piano) {
  const kpi = piano.kpi || {};
  if (!piano.giri.length) {
    document.getElementById('kpi-piano').innerHTML =
      '<p class="vuoto">Nessun ordine da pianificare nell&rsquo;intervallo selezionato.</p>';
    document.getElementById('scheda-confronto').hidden = true;
    tabella(document.getElementById('tabella-giri'), [{ titolo: 'Giri', valore: () => '' }], []);
    return;
  }

  document.getElementById('kpi-piano').innerHTML = [
    schedaKpi('Spedizioni pianificate', numero(kpi.spedizioni)),
    schedaKpi('Giri generati', numero(kpi.giri), `${numero(kpi.fermate)} fermate`),
    schedaKpi('Km totali', numero(kpi.km_totali), `${numero(kpi.km_per_fermata, 1)} km/fermata`),
    schedaKpi('Costo di piano', euro(kpi.costo_totale_eur), 'flotta propria'),
    schedaKpi('Costo ottimizzato', euro(kpi.costo_ottimizzato_eur), 'con make or buy', 'positivo'),
    schedaKpi('Costo per km', euroPreciso(kpi.costo_per_km)),
    schedaKpi('Costo per pallet', euroPreciso(kpi.costo_per_pallet)),
    schedaKpi('Costo per ton-km', euroPreciso(kpi.costo_per_ton_km)),
    schedaKpi('Saturazione media', `${numero(kpi.saturazione_media_pct, 1)}%`, `${numero(kpi.giri_sottosaturi)} giri sottosaturi`,
      kpi.saturazione_media_pct < 60 ? 'attenzione' : 'positivo'),
    schedaKpi('CO₂ stimata', `${numero(kpi.co2_kg)} kg`, `${numero(kpi.co2_g_per_ton_km, 1)} g/ton-km`),
    schedaKpi('Giri su più giorni', numero(kpi.giri_multigiorno),
      kpi.costo_traghetti_eur ? `${euro(kpi.costo_traghetti_eur)} di traghetti` : 'nessun collegamento marittimo'),
  ].join('');

  const confronto = piano.confronto || {};
  const base = piano.scenario_base || {};
  document.getElementById('scheda-confronto').hidden = false;
  document.getElementById('confronto-piano').innerHTML = `
    <div class="voce-confronto">
      <div class="etichetta">Scenario senza ottimizzazione</div>
      <div>${numero(base.missioni)} missioni dedicate</div>
      <div>${numero(base.km)} km · ${euro(base.costo_eur)}</div>
    </div>
    <div class="voce-confronto">
      <div class="etichetta">Km risparmiati</div>
      <div class="valore-grande">${numero(confronto.km_risparmiati)}</div>
      <div>${numero(confronto.km_risparmiati_pct, 1)}% in meno</div>
    </div>
    <div class="voce-confronto">
      <div class="etichetta">Risparmio economico</div>
      <div class="valore-grande">${euro(confronto.costo_risparmiato_eur)}</div>
      <div>${numero(confronto.costo_risparmiato_pct, 1)}% del costo di partenza</div>
    </div>
    <div class="voce-confronto">
      <div class="etichetta">Di cui da consolidamento</div>
      <div class="valore-grande">${euro(confronto.risparmio_da_consolidamento_eur)}</div>
      <div>${euro(confronto.risparmio_da_make_or_buy_eur)} da scelta vettore</div>
    </div>
    <div class="voce-confronto">
      <div class="etichetta">CO₂ evitata</div>
      <div class="valore-grande">${numero(confronto.co2_risparmiata_kg)} kg</div>
      <div>${numero(confronto.missioni_evitate)} missioni in meno</div>
    </div>`;

  tabella(document.getElementById('tabella-giri'), [
    { titolo: 'Giro', valore: (g) => `<strong>${g.id}</strong><br><small>${g.data}</small>` },
    { titolo: 'Partenza', valore: (g) => `${g.origine_codice}<br><small>${g.veicolo_descrizione}</small>` },
    { titolo: 'Fermate', numero: true, valore: (g) => numero(g.sequenza.length) },
    { titolo: 'Km', numero: true, valore: (g) => numero(g.km) },
    {
      titolo: 'Durata',
      numero: true,
      valore: (g) => `${numero(g.durata_ore, 1)} h${g.giorni_impegno > 1 ? `<br><small>${numero(g.giorni_impegno)} giorni</small>` : ''}`,
    },
    { titolo: 'Satur.', numero: true, valore: (g) => `${numero(g.saturazione_pct, 1)}%` },
    { titolo: 'Costo', numero: true, valore: (g) => euro(g.costo.totale) },
    {
      titolo: 'Scelta',
      valore: (g) => `<span class="etichetta-stato stato-${g.scelta_consigliata.toLowerCase()}">${
        g.scelta_consigliata === 'PROPRIO' ? 'conto proprio' : 'conto terzi'}</span>`,
    },
  ], piano.giri, {
    selezionabile: true,
    alClick: (giro) => mostraDettaglioGiro(giro),
  });

  if (stato.siti.length) disegnaMappa(stato.siti, piano.giri);
}

function mostraDettaglioGiro(giro) {
  const tappe = giro.cronoprogramma
    .map((t, i) => {
      const nome = i < giro.fermate_nomi.length ? giro.fermate_nomi[i] : `Rientro a ${giro.origine_nome}`;
      return `<tr><td>${i + 1}</td><td>${nome}</td><td class="numero">g${t.giorno}</td>
        <td class="numero">${ora(t.arrivo)}</td>
        <td class="numero">${t.partenza === null ? '-' : ora(t.partenza)}</td>
        <td class="numero">${numero(t.km_progressivi)}</td></tr>`;
    })
    .join('');

  const costo = giro.costo;
  document.getElementById('dettaglio-giro').innerHTML = `
    <dl>
      <dt>Giro</dt><dd>${giro.id} · ${giro.data}</dd>
      <dt>Partenza</dt><dd>${giro.origine_nome}</dd>
      <dt>Mezzo</dt><dd>${giro.veicolo_descrizione}</dd>
      <dt>Carico</dt><dd>${numero(giro.peso_kg)} kg · ${numero(giro.volume_m3, 1)} m³ · ${numero(giro.pallet, 1)} pallet</dd>
      <dt>Saturazione</dt><dd>${numero(giro.saturazione_pct, 1)}%</dd>
      <dt>Percorrenza</dt><dd>${numero(giro.km)} km in ${numero(giro.durata_ore, 1)} h (guida ${numero(giro.ore_guida, 1)} h)</dd>
      <dt>Impegno</dt><dd>${numero(giro.giorni_impegno)} giorno/i${giro.ore_traghetto ? ` · traghetto ${numero(giro.ore_traghetto, 1)} h` : ''}</dd>
      <dt>CO₂</dt><dd>${numero(giro.co2_kg)} kg</dd>
    </dl>
    ${giro.violazioni && giro.violazioni.length
      ? `<div class="kpi critico"><div class="etichetta">Vincoli non rispettati</div>
          <ul>${giro.violazioni.map((v) => `<li>${v}</li>`).join('')}</ul></div>`
      : ''}
    <h4>Cronoprogramma</h4>
    <table><thead><tr><th>#</th><th>Fermata</th><th class="numero">Giorno</th><th class="numero">Arrivo</th><th class="numero">Partenza</th><th class="numero">Km</th></tr></thead>
      <tbody>${tappe}</tbody></table>
    <h4>Struttura del costo</h4>
    <div class="riga-costo"><span>Carburante</span><span>${euroPreciso(costo.carburante)}</span></div>
    <div class="riga-costo"><span>Pedaggi</span><span>${euroPreciso(costo.pedaggi)}</span></div>
    <div class="riga-costo"><span>Manutenzione</span><span>${euroPreciso(costo.manutenzione)}</span></div>
    <div class="riga-costo"><span>Personale</span><span>${euroPreciso(costo.personale)}</span></div>
    <div class="riga-costo"><span>Costi fissi mezzo</span><span>${euroPreciso(costo.costi_fissi)}</span></div>
    ${costo.traghetti ? `<div class="riga-costo"><span>Traghetti</span><span>${euroPreciso(costo.traghetti)}</span></div>` : ''}
    <div class="riga-costo totale"><span>Totale conto proprio</span><span>${euroPreciso(costo.totale)}</span></div>
    <div class="riga-costo"><span>Alternativa conto terzi</span><span>${euroPreciso(giro.costo_conto_terzi)}</span></div>`;
}

document.getElementById('genera-piano').addEventListener('click', generaPiano);

/* ---------------------------------------------------------- simulatore */
function popolaSelettori() {
  const interni = stato.siti.filter((s) => s.tipo !== 'CLIENTE');
  const opzioniOrigine = interni.map((s) => `<option value="${s.id}">${s.codice} - ${s.nome}</option>`).join('');
  const opzioniDestino = stato.siti.map((s) => `<option value="${s.id}">${s.codice} - ${s.nome}</option>`).join('');
  document.getElementById('sim-origine').innerHTML = opzioniOrigine;
  document.getElementById('sim-destino').innerHTML = opzioniDestino;
  const opzioniProfilo = stato.profili
    .map((p) => `<option value="${p.codice}">${p.descrizione} (${numero(p.portata_kg)} kg / ${p.posti_pallet} pl)</option>`)
    .join('');
  document.getElementById('sim-profilo').innerHTML = opzioniProfilo;
  document.getElementById('piano-profilo').innerHTML = opzioniProfilo;
  document.getElementById('piano-profilo').value = 'MOTRICE_180';
  document.getElementById('sim-profilo').value = 'MOTRICE_180';
}

document.getElementById('modulo-simulatore').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const corpo = {
    origine_id: Number(document.getElementById('sim-origine').value),
    destino_id: Number(document.getElementById('sim-destino').value),
    peso_kg: Number(document.getElementById('sim-peso').value),
    volume_m3: Number(document.getElementById('sim-volume').value),
    pallet: Number(document.getElementById('sim-pallet').value),
    profilo: document.getElementById('sim-profilo').value,
    sconto_vettore_pct: Number(document.getElementById('sim-sconto').value) / 100,
    andata_ritorno: document.getElementById('sim-ar').checked,
  };
  try {
    const esito = await api('/api/simulazioni/make-or-buy', { method: 'POST', body: JSON.stringify(corpo) });
    const proprio = esito.conto_proprio;
    const vinceProprio = esito.scelta_consigliata === 'PROPRIO';
    document.getElementById('esito-simulazione').innerHTML = `
      <p class="nota">${esito.origine} → ${esito.destino} · ${numero(esito.km_totali)} km ·
        ${numero(esito.ore_guida, 1)} h di guida · ${esito.veicolo}${
        esito.traghetto ? ` · traghetto ${esito.traghetto} (${numero(esito.ore_traghetto, 1)} h)` : ''}</p>
      <div class="risultato-confronto">
        <div class="blocco ${vinceProprio ? 'vincente' : ''}">
          <h4>Conto proprio</h4>
          <div class="riga-costo"><span>Carburante</span><span>${euroPreciso(proprio.carburante)}</span></div>
          <div class="riga-costo"><span>Pedaggi</span><span>${euroPreciso(proprio.pedaggi)}</span></div>
          <div class="riga-costo"><span>Manutenzione</span><span>${euroPreciso(proprio.manutenzione)}</span></div>
          <div class="riga-costo"><span>Personale</span><span>${euroPreciso(proprio.personale)}</span></div>
          <div class="riga-costo"><span>Costi fissi</span><span>${euroPreciso(proprio.costi_fissi)}</span></div>
          ${proprio.traghetti ? `<div class="riga-costo"><span>Traghetti</span><span>${euroPreciso(proprio.traghetti)}</span></div>` : ''}
          <div class="riga-costo totale"><span>Totale</span><span>${euroPreciso(proprio.totale)}</span></div>
        </div>
        <div class="blocco ${vinceProprio ? '' : 'vincente'}">
          <h4>Conto terzi</h4>
          <div class="riga-costo"><span>Tariffa a scaglioni</span><span>${euroPreciso(esito.conto_terzi.vettore)}</span></div>
          <div class="riga-costo"><span>Fuel surcharge incluso</span><span>sì</span></div>
          <div class="riga-costo totale"><span>Totale</span><span>${euroPreciso(esito.conto_terzi.totale)}</span></div>
        </div>
      </div>
      <div class="kpi positivo">
        <div class="etichetta">Scelta consigliata</div>
        <div class="valore">${vinceProprio ? 'Flotta propria' : 'Vettore terzo'}</div>
        <div class="nota-kpi">Differenza ${euroPreciso(esito.risparmio_eur)} ·
          saturazione peso ${numero(esito.saturazione_peso_pct, 1)}% · CO₂ ${numero(esito.co2_kg)} kg</div>
      </div>`;
  } catch (errore) {
    alert(`Errore nella simulazione: ${errore.message}`);
  }
});

/* ------------------------------------------------------------- avvio */
(async function avvia() {
  try {
    const [statoSistema, siti, profili] = await Promise.all([
      api('/api/stato'),
      api('/api/siti'),
      api('/api/profili-veicolo'),
    ]);
    stato.siti = siti;
    stato.profili = profili;
    document.getElementById('stato-sistema').textContent =
      `${statoSistema.conteggi.siti} siti · ${statoSistema.conteggi.articoli} articoli · ${statoSistema.conteggi.ordini} ordini`;
    popolaSelettori();
    caricate.add('cruscotto');
    await caricaCruscotto();
  } catch (errore) {
    document.getElementById('stato-sistema').textContent = `Errore: ${errore.message}`;
  }
})();
