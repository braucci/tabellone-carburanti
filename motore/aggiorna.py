"""Tabellone Carburanti — aggiornamento di data/prezzi.json (strato di I/O).

Uso tipico (è ciò che esegue GitHub Actions ogni mattina):

    python3 -m motore.aggiorna --json data/prezzi.json

Prova senza rete, con una pagina salvata in locale:

    python3 -m motore.aggiorna --json /tmp/prova.json \\
        --pagina motore/campioni/pagina_autostrade.html --oggi 2026-10-19

Comportamento in rete
---------------------
* User-Agent identificativo con l'indirizzo del progetto;
* rispetto di robots.txt secondo RFC 9309: un robots.txt assente (4xx)
  consente l'accesso, uno irraggiungibile (5xx o rete) lo vieta;
* tre tentativi con attesa crescente sugli errori transitori;
* una sola richiesta alla pagina per esecuzione.

Codici d'uscita: 0 se la pagina è stata letta (anche se non ancora
aggiornata), 1 se non è stato possibile leggerla, 2 se il JSON prodotto viola
un invariante (il file precedente resta intatto).

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

from . import __version__, core

ROMA = ZoneInfo("Europe/Rome")

URL_PAGINA = "https://www.mimit.gov.it/it/prezzo-medio-carburanti/autostrade"
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

def carica_json(percorso: Path) -> dict | None:
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    # Uno storico in un formato precedente non è riutilizzabile: si riparte.
    return dati if dati.get("schema") == core.SCHEMA else None


def scrivi_atomico(percorso: Path, dati: dict) -> None:
    """Scrive su un file temporaneo e poi lo rinomina: un'interruzione a metà
    non lascia mai un JSON troncato."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    testo = json.dumps(dati, ensure_ascii=False, indent=1) + "\n"
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

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aggiorna data/prezzi.json dalla pagina MIMIT.")
    ap.add_argument("--json", type=Path, default=Path("data/prezzi.json"))
    ap.add_argument("--pagina", type=Path, help="pagina HTML salvata in locale (salta la rete)")
    ap.add_argument("--oggi", type=date.fromisoformat, help="data odierna (per le prove)")
    args = ap.parse_args(argv)

    adesso = datetime.now(ROMA)
    if args.oggi:
        adesso = datetime.combine(args.oggi, adesso.time(), ROMA)
    oggi = adesso.date()

    precedente = carica_json(args.json)
    storico: dict = dict(precedente.get("storico", {})) if precedente else {}
    fonte: dict = {"url": URL_PAGINA}

    print(f"Tabellone Carburanti {__version__} — {adesso:%d/%m/%Y %H:%M}")
    try:
        html = args.pagina.read_bytes() if args.pagina else scarica(URL_PAGINA)
        ris = core.leggi_pagina_ufficiale(html, oggi)
    except Exception as e:  # noqa: BLE001 — l'errore va riportato nel log, non propagato
        motivo = f"saltata: {e}" if isinstance(e, Vietato) else f"errore: {type(e).__name__}: {e}"
        print(f" • pagina MIMIT: {motivo}")
        if isinstance(e, Vietato):
            r = robots_di(URL_PAGINA)
            print(f"   robots.txt: {r.stato}; agente: {AGENTE}")
            if r.direttive:
                print("   direttive di robots.txt (senza commenti):")
                for riga in r.direttive[:80]:
                    print(f"     {riga}")
        print("Il file esistente resta invariato.")
        return 1

    if not ris.voci:
        print(" • pagina MIMIT: nessuna riga riconosciuta (TIPOLOGIA | EROGAZIONE | PREZZO MEDIO).")
        print("   La struttura della pagina potrebbe essere cambiata: il file resta invariato.")
        return 1

    print(f" • pagina MIMIT letta: {ris.data:%d/%m/%Y}{' (data non indicata: si assume oggi)' if ris.data_dedotta else ''}")
    for c in core.CARBURANTI:
        v = ris.voci.get(c)
        print(f"     {core.NOMI[c]:<8} {v['erogazione']:<8} {v['prezzo']:.3f} {core.UNITA[c]}" if v
              else f"     {core.NOMI[c]:<8} assente nella pagina")

    invariata = core.pagina_invariata(storico, ris)
    if invariata:
        print(f" • valori identici a quelli del {invariata}: pagina probabilmente non ancora aggiornata,"
              " nessun nuovo giorno registrato.")
        fonte.update(esito=f"pagina invariata rispetto al {invariata}")
    else:
        core.integra(storico, ris.data, ris.voci)
        fonte.update(esito="ok", data=ris.data.isoformat(), data_dedotta=ris.data_dedotta)

    storico = core.pota(storico, oggi)
    dati = core.componi(storico, fonte, adesso, __version__)
    try:
        core.controlla_invarianti(dati)
    except AssertionError as e:
        print(f"Invariante violato, file NON scritto: {e}")
        return 2

    if core.contenuto_equivalente(precedente, dati):
        print("Nessun dato nuovo: file invariato.")
    else:
        scrivi_atomico(args.json, dati)
        print(f"Scritto {args.json}")

    for r in dati["tabellone"]:
        prezzo = "  —  " if r["prezzo"] is None else f"{r['prezzo']:.3f}"
        var = "" if r["variazione"] is None else f"{r['variazione'] * 1000:+.0f} m€"
        print(f"   {r['carburante']:<8}{r['erogazione'] or '':<8}{prezzo} {r['unita']:<5} {var:<8} {r['data'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
