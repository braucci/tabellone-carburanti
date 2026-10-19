# Tabellone Carburanti

I prezzi medi ufficiali di **gasolio**, **benzina**, **GPL** e **metano** sulla
rete autostradale italiana, mostrati come su un tabellone ferroviario a
palette: all'apertura le palette girano e compongono i prezzi del giorno.

<p align="center"><img src="docs/tabellone.png" width="354" alt="Il tabellone sul telefono"></p>

- **Valori come pubblicati dal Ministero**, con l'erogazione indicata dalla
  pagina (self per gasolio e benzina, servito per GPL e metano): nessun calcolo,
  nessuna stima.
- **App web installabile** sul telefono (Android e iPhone), funziona anche offline.
- **Aggiornamento automatico** dal Mac di casa, che legge il CSV ufficiale più
  volte al giorno e pubblica i dati nel repository; GitHub Actions rimette
  online il sito a ogni aggiornamento.

**Apri il tabellone:** <https://braucci.github.io/tabellone-carburanti/>

## Installazione sul telefono

- **Android (Chrome):** apri il link, menu ⋮ → *Installa app* (o *Aggiungi a schermata Home*).
- **iPhone (Safari):** apri il link, pulsante Condividi → *Aggiungi alla schermata Home*.

## Aggiornamento automatico sul Mac

```bash
cd ~/Downloads/tabellone-carburanti
bash strumenti/macos/installa.sh
```

Serve un token GitHub *fine-grained* con il solo permesso *Contents: Read and
write* su questo repository: la procedura completa è nel README-progetto,
sezione 5.

## Prova in locale

```bash
./verifica.sh            # prove automatiche, senza rete
./verifica.sh --servi    # e poi anteprima su http://<ip-del-pc>:8000
```

Serve solo Python 3.10 o successivo, senza librerie aggiuntive.

## Documentazione

Architettura, regole di lettura dei dati con le relative giustificazioni,
pubblicazione passo passo su GitHub e manutenzione:
**[README-progetto.md](README-progetto.md)**.

## Fonti e licenze

- Dati: Osservatorio prezzi carburanti, Ministero delle Imprese e del Made in
  Italy — [Prezzi medi dei carburanti – Autostrade](https://www.mimit.gov.it/it/prezzo-medio-carburanti/autostrade)
  e il relativo file «Media prezzi alle 8 (csv)».
- Caratteri: Barlow, Barlow Condensed, DotGothic16 (SIL Open Font License).
- Codice: licenza MIT © 2026 Biagio Raucci.
