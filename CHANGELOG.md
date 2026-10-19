# Registro delle modifiche

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/);
numerazione [semantica](https://semver.org/lang/it/).

## [1.2.0] — 2026-10-19

### Modificato
- La lettura dei dati passa dal Mac: il sito del Ministero non risponde ai
  server di GitHub (robots.txt in timeout), mentre risponde dall'Italia e le
  sue regole consentono le pagine usate.
- Il workflow «Pubblica tabellone» non legge più il MIMIT: a ogni commit
  esegue le prove, controlla gli invarianti dei dati e pubblica il sito.

### Aggiunto
- Fonte principale: il CSV ufficiale MediaNazionaleAutostradale.csv, con la
  data esplicita della rilevazione; la pagina HTML resta come riserva.
- `motore/deposito.py`: lettura e scrittura di data/prezzi.json tramite l'API
  "contents" di GitHub, con controllo dello sha e nuova lettura in caso di
  conflitto; token dalla variabile TABELLONE_TOKEN o dal Portachiavi.
- Opzioni `--github`, `--csv` e `--verifica-github` del motore.
- `strumenti/macos/installa.sh` e `disinstalla.sh`: LaunchAgent di launchd
  (9:40, 11:40, 15:10, 19:10 e a ogni accesso), token nel Portachiavi,
  registro in ~/Library/Logs/TabelloneCarburanti.log.
- 11 prove nuove (32 in tutto), con il CSV reale del 19/10/2026 fra i campioni.

## [1.1.1] — 2026-10-19

### Modificato
- Diagnostica di `robots.txt` nel log: distingue un divieto esplicito da un
  `robots.txt` irraggiungibile e, nel primo caso, stampa lo stato della
  lettura e le direttive User-agent / Allow / Disallow del sito.

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
