"""Tabellone Carburanti — aggiornamento di data/prezzi.json (strato di I/O).

Uso tipico, sul Mac (è ciò che esegue launchd più volte al giorno):

    python3 -m motore.aggiorna --github braucci/tabellone-carburanti

legge le medie ufficiali MIMIT e, se ci sono dati nuovi, sostituisce
data/prezzi.json nel repository con un commit; il commit fa ripartire il
workflow di GitHub che pubblica il sito.

Uso locale, su un file:

    python3 -m motore.aggiorna --json data/prezzi.json

Prova senza rete, con i campioni:

    python3 -m motore.aggiorna --json /tmp/prova.json \\
        --csv motore/campioni/MediaNazionaleAutostradale.csv --oggi 2026-10-19

Fonti, in ordine: il CSV ufficiale MediaNazionaleAutostradale.csv, poi la
pagina HTML delle medie autostradali come riserva.

Comportamento in rete
---------------------
* User-Agent identificativo con l'indirizzo del progetto;
* rispetto di robots.txt secondo RFC 9309: un robots.txt assente (4xx)
  consente l'accesso, uno irraggiungibile (5xx o rete) lo vieta;
* tre tentativi con attesa crescente sugli errori transitori;
* una richiesta per fonte e per esecuzione.

Codici d'uscita: 0 se una fonte è stata letta (anche se non ancora
aggiornata), 1 se nessuna fonte o GitHub non sono raggiungibili, 2 se il JSON
prodotto viola un invariante (i dati pubblicati restano intatti).

Autore: Biagio Raucci — Licenza MIT.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

from . import __version__, core, deposito

ROMA = ZoneInfo("Europe/Rome")

URL_CSV = "https://www.mimit.gov.it/images/stories/carburanti/MediaNazionaleAutostradale.csv"
URL_PAGINA = "https://www.mimit.gov.it/it/prezzo-medio-carburanti/autostrade"
PERCORSO_DATI = "data/prezzi.json"
URL_PROGETTO = "https://github.com/braucci/tabellone-carburanti"

AGENTE = f"TabelloneCarburanti/{__version__} (+{URL_PROGETTO})"


class Vietato(Exception):
    """L'accesso alla risorsa non è consentito da robots.txt."""


# ---------------------------------------------------------------------------
# Rete
# ---------------------------------------------------------------------------

def _richiesta(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": AGENTE, "Accept-Encoding": "gzip", "Accept": "text/html,*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as risposta:
        dati = risposta.read()
        if risposta.headers.get("Content-Encoding", "").lower() == "gzip":
            dati = gzip.decompress(dati)
        return dati


@dataclass
class Robots:
    """Regole di robots.txt per un sito, con lo stato della lettura (per il log)."""

    regole: RobotFileParser
    stato: str                       # es. "letto (HTTP 200)"
    irraggiungibile: bool = False    # vero se il divieto nasce dall'assenza di risposta
    direttive: list[str] = field(default_factory=list)


_robots: dict[str, Robots] = {}


def _direttive(testo: str) -> list[str]:
    """Le sole righe User-agent / Allow / Disallow, senza commenti: bastano per capire la regola."""
    righe = []
    for riga in testo.splitlines():
        riga = riga.split("#", 1)[0].strip()
        if riga.lower().startswith(("user-agent", "allow", "disallow")):
            righe.append(riga)
    return righe


def robots_di(url: str) -> Robots:
    p = urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base in _robots:
        return _robots[base]
    rp = RobotFileParser(base + "/robots.txt")
    try:
        testo = _richiesta(base + "/robots.txt", timeout=30).decode("utf-8", "replace")
        rp.parse(testo.splitlines())
        r = Robots(rp, "letto (HTTP 200)", direttive=_direttive(testo))
    except urllib.error.HTTPError as e:
        rp.parse([])
        if 400 <= e.code < 500:
            rp.allow_all = True       # RFC 9309 §2.3.1.3: "unavailable" → accesso consentito
            r = Robots(rp, f"assente (HTTP {e.code}): accesso consentito")
        else:
            rp.disallow_all = True    # RFC 9309 §2.3.1.4: "unreachable" → accesso vietato
            r = Robots(rp, f"irraggiungibile (HTTP {e.code})", irraggiungibile=True)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        rp.parse([])
        rp.disallow_all = True
        r = Robots(rp, f"irraggiungibile ({type(e).__name__}: {e})", irraggiungibile=True)
    _robots[base] = r
    return r


def consentito(url: str) -> bool:
    return robots_di(url).regole.can_fetch(AGENTE, url)


def scarica(url: str, tentativi: int = 3) -> bytes:
    r = robots_di(url)
    if not r.regole.can_fetch(AGENTE, url):
        if r.irraggiungibile:
            raise Vietato(f"robots.txt {r.stato}: secondo la RFC 9309 l'accesso va considerato vietato")
        raise Vietato(f"robots.txt non consente l'accesso a {url}")
    attesa = 10
    for n in range(1, tentativi + 1):
        try:
            return _richiesta(url)
        except urllib.error.HTTPError as e:
            if e.code < 500 or n == tentativi:
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if n == tentativi:
                raise
        print(f"   tentativo {n} fallito su {url}; nuovo tentativo fra {attesa} s")
        time.sleep(attesa)
        attesa *= 3
    raise RuntimeError("non raggiungibile")  # pragma: no cover


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------

def da_testo(testo: str | None) -> dict | None:
    if not testo:
        return None
    dati = json.loads(testo)
    # Uno storico in un formato precedente non è riutilizzabile: si riparte.
    return dati if dati.get("schema") == core.SCHEMA else None


def carica_json(percorso: Path) -> dict | None:
    try:
        return da_testo(percorso.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def in_testo(dati: dict) -> str:
    return json.dumps(dati, ensure_ascii=False, indent=1) + "\n"


def scrivi_atomico(percorso: Path, dati: dict) -> None:
    """Scrive su un file temporaneo e poi lo rinomina: un'interruzione a metà
    non lascia mai un JSON troncato."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    testo = in_testo(dati)
    fd, tmp = tempfile.mkstemp(dir=percorso.parent, prefix=".prezzi-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(testo)
        os.replace(tmp, percorso)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Programma
# ---------------------------------------------------------------------------

def _spiega_robots(url: str) -> None:
    r = robots_di(url)
    print(f"   robots.txt: {r.stato}; agente: {AGENTE}")
    if r.direttive:
        print("   direttive di robots.txt (senza commenti):")
        for riga in r.direttive[:80]:
            print(f"     {riga}")


def acquisisci(args, oggi: date) -> tuple[core.RisultatoUfficiale, dict] | None:
    """Prova le fonti in ordine: CSV ufficiale, poi pagina HTML. Con file locali
    (--csv, --pagina) usa solo quelli. Restituisce (risultato, fonte) o None."""
    if args.csv or args.pagina:
        fonti = [(f, "csv" if f is args.csv else "html", str(f)) for f in (args.csv, args.pagina) if f]
    else:
        fonti = [(None, "csv", URL_CSV), (None, "html", URL_PAGINA)]
    for locale, formato, indirizzo in fonti:
        nome = "CSV MIMIT" if formato == "csv" else "pagina MIMIT"
        try:
            dati = locale.read_bytes() if locale else scarica(indirizzo)
            leggi = core.leggi_csv_ufficiale if formato == "csv" else core.leggi_pagina_ufficiale
            ris = leggi(dati, oggi)
        except Exception as e:  # noqa: BLE001 — l'errore va riportato nel log, non propagato
            vietato = isinstance(e, Vietato)
            print(f" • {nome}: {'saltata' if vietato else 'errore'}: "
                  f"{e if vietato else f'{type(e).__name__}: {e}'}")
            if vietato and not locale:
                _spiega_robots(indirizzo)
            continue
        if not ris.voci:
            print(f" • {nome}: nessuna riga riconosciuta (TIPOLOGIA | EROGAZIONE | PREZZO MEDIO)")
            continue
        nota = " (data non indicata: si assume oggi)" if ris.data_dedotta else ""
        print(f" • {nome} letto: rilevazione del {ris.data:%d/%m/%Y}{nota}")
        for c in core.CARBURANTI:
            v = ris.voci.get(c)
            print(f"     {core.NOMI[c]:<8} {v['erogazione']:<8} {v['prezzo']:.3f} {core.UNITA[c]}" if v
                  else f"     {core.NOMI[c]:<8} assente")
        return ris, {"url": indirizzo, "formato": formato}
    return None


def nuovi_dati(precedente: dict | None, ris: core.RisultatoUfficiale, fonte: dict,
               adesso: datetime) -> dict:
    storico = dict(precedente.get("storico", {})) if precedente else {}
    fonte = dict(fonte)
    invariata = core.pagina_invariata(storico, ris)
    if invariata:
        print(f" • valori identici a quelli del {invariata}: fonte probabilmente non ancora aggiornata,"
              " nessun nuovo giorno registrato.")
        fonte.update(esito=f"invariata rispetto al {invariata}")
    else:
        core.integra(storico, ris.data, ris.voci)
        fonte.update(esito="ok", data=ris.data.isoformat(), data_dedotta=ris.data_dedotta)
    storico = core.pota(storico, adesso.date())
    return core.componi(storico, fonte, adesso, __version__)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aggiorna data/prezzi.json dai dati ufficiali MIMIT.")
    ap.add_argument("--json", type=Path, default=Path(PERCORSO_DATI),
                    help="file locale da aggiornare (ignorato con --github)")
    ap.add_argument("--github", metavar="PROPRIETARIO/REPO",
                    help="legge e scrive data/prezzi.json direttamente nel repository GitHub")
    ap.add_argument("--csv", type=Path, help="CSV MIMIT salvato in locale (salta la rete)")
    ap.add_argument("--pagina", type=Path, help="pagina HTML salvata in locale (salta la rete)")
    ap.add_argument("--oggi", type=date.fromisoformat, help="data odierna (per le prove)")
    ap.add_argument("--verifica-github", action="store_true",
                    help="controlla solo che il token legga i dati del repository, senza scrivere nulla")
    args = ap.parse_args(argv)

    if args.verifica_github:
        if not args.github:
            ap.error("--verifica-github richiede --github PROPRIETARIO/REPO")
        try:
            testo, _ = deposito.leggi(args.github, PERCORSO_DATI, deposito.token())
        except (deposito.ErroreGitHub, urllib.error.URLError, OSError) as e:
            print(f"GitHub: {e}")
            return 1
        dati = da_testo(testo)
        quando = dati["rilevazione"] if dati else "nessun dato ancora pubblicato"
        print(f"GitHub: accesso a {args.github} riuscito (rilevazione pubblicata: {quando}).")
        return 0

    adesso = datetime.now(ROMA)
    if args.oggi:
        adesso = datetime.combine(args.oggi, adesso.time(), ROMA)
    print(f"Tabellone Carburanti {__version__} — {adesso:%d/%m/%Y %H:%M}")

    acquisito = acquisisci(args, adesso.date())
    if acquisito is None:
        print("Nessuna fonte disponibile: i dati pubblicati restano invariati.")
        return 1
    ris, fonte = acquisito

    try:
        tok = deposito.token() if args.github else None
    except deposito.ErroreGitHub as e:
        print(f" • GitHub: {e}")
        return 1

    for tentativo in (1, 2):
        try:
            if args.github:
                testo, sha = deposito.leggi(args.github, PERCORSO_DATI, tok)
                precedente = da_testo(testo)
            else:
                precedente, sha = carica_json(args.json), None
            dati = nuovi_dati(precedente, ris, fonte, adesso)
            try:
                core.controlla_invarianti(dati)
            except AssertionError as e:
                print(f"Invariante violato, dati NON scritti: {e}")
                return 2
            if core.contenuto_equivalente(precedente, dati):
                print("Nessun dato nuovo: file invariato.")
            elif args.github:
                messaggio = f"Prezzi del {date.fromisoformat(dati['rilevazione']):%d/%m/%Y}"
                commit = deposito.scrivi(args.github, PERCORSO_DATI, tok, in_testo(dati), sha, messaggio)
                print(f"Pubblicato su GitHub ({args.github}): «{messaggio}», commit {commit[:7]}")
            else:
                scrivi_atomico(args.json, dati)
                print(f"Scritto {args.json}")
            break
        except deposito.Conflitto as e:
            if tentativo == 2:
                print(f" • GitHub: {e}; riprova alla prossima esecuzione.")
                return 1
            print(f" • GitHub: {e}; rileggo e riprovo.")
        except (deposito.ErroreGitHub, urllib.error.URLError, OSError) as e:
            print(f" • GitHub: {e}")
            return 1

    for r in dati["tabellone"]:
        prezzo = "  —  " if r["prezzo"] is None else f"{r['prezzo']:.3f}"
        var = "" if r["variazione"] is None else f"{r['variazione'] * 1000:+.0f} m€"
        print(f"   {r['carburante']:<8}{r['erogazione'] or '':<8}{prezzo} {r['unita']:<5} {var:<8} {r['data'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
