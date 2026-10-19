# Registro delle modifiche

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/);
numerazione [semantica](https://semver.org/lang/it/).

## [1.1.0] — 2026-10-19

### Modificato
- Il tabellone riporta esattamente la tabella della pagina MIMIT: gasolio,
  benzina, GPL e metano, con l'erogazione letta dalla pagina (self o servito)
  e l'unità di misura (€/L, €/kg per il metano).
- La data della rilevazione compare nella testata; la colonna di destra
  mostra l'unità di misura.
- Formato dei dati: schema 2 (uno storico per carburante con erogazione).
- Nome dell'autore per esteso: Biagio Raucci.

### Aggiunto
- Targa con il nome Biagio Raucci sul tabellone, come la targa del costruttore
  dei tabelloni Solari; nome anche nella riga LED.
- Riconoscimento della pagina non ancora aggiornata: se la pagina non riporta
  una data e i quattro valori coincidono con il giorno precedente, il nuovo
  giorno non viene registrato.
- Animazione guidata dal tempo con un solo ciclo `requestAnimationFrame`:
  stessa velocità a 60 e 120 Hz.

### Rimosso
- Il calcolo delle medie dagli open data (self e servito di benzina e
  gasolio) e la relativa verifica: il tabellone mostra solo valori pubblicati.

## [1.0.0] — 2026-10-19

### Aggiunto
- Tabellone a palette in stile Solari: animazione d'apertura che compone
  carburante, erogazione, prezzo e variazione; orologio a palette; riga LED
  scorrevole con fonte, date e verifica del metodo.
- Quattro serie: gasolio e benzina, self e servito, rete autostradale.
- Motore Python senza dipendenze (`motore/`): lettura della pagina ufficiale
  MIMIT (media self) e degli open data MIMIT (media self e servito calcolate),
  storico di 400 giorni, variazioni omogenee per origine, scarto del metodo,
  invarianti verificati prima di ogni scrittura, scrittura atomica.
- Rispetto di robots.txt secondo RFC 9309 e User-Agent identificativo.
- Workflow GitHub Actions: prove, acquisizione due volte al giorno,
  archiviazione dei dati, pubblicazione su GitHub Pages.
- App installabile (manifest e service worker) con funzionamento offline.
- Suono facoltativo delle palette, rispetto di "riduci movimento".
- 24 prove automatiche su campioni sintetici; script `verifica.sh`.
