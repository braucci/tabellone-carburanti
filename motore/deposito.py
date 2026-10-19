"""Tabellone Carburanti — lettura e scrittura di data/prezzi.json su GitHub.

Si usa l'API REST "contents" di GitHub, che legge e sostituisce un singolo
file del repository senza bisogno di git sul computer:

    GET  /repos/{proprietario}/{repo}/contents/{percorso}   → contenuto + sha
    PUT  /repos/{proprietario}/{repo}/contents/{percorso}   ← contenuto + sha

Lo sha è l'impronta della versione letta: se nel frattempo il file è cambiato,
GitHub rifiuta la scrittura (409) invece di sovrascrivere, e il motore rilegge.

Il token (fine-grained, con il solo permesso Contents: Read and write sul
repository) si cerca nella variabile d'ambiente TABELLONE_TOKEN oppure, sul
Mac, nel Portachiavi alla voce "tabellone-carburanti".

Autore: Biagio Raucci — Licenza MIT.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

from . import __version__

API = "https://api.github.com"
SERVIZIO_PORTACHIAVI = "tabellone-carburanti"
AGENTE = f"TabelloneCarburanti/{__version__}"


class Conflitto(Exception):
    """Il file è cambiato su GitHub fra la lettura e la scrittura."""


class ErroreGitHub(Exception):
    """Risposta inattesa dall'API di GitHub, con una spiegazione leggibile."""


def token() -> str:
    """Il token di accesso: prima la variabile d'ambiente, poi il Portachiavi del Mac."""
    t = os.environ.get("TABELLONE_TOKEN", "").strip()
    if t:
        return t
    if sys.platform == "darwin":
        r = subprocess.run(
            ["security", "find-generic-password", "-s", SERVIZIO_PORTACHIAVI, "-w"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    raise ErroreGitHub(
        "token GitHub non trovato: impostare TABELLONE_TOKEN oppure eseguire "
        "strumenti/macos/installa.sh, che lo salva nel Portachiavi"
    )


def _chiama(metodo: str, url: str, tok: str, corpo: dict | None = None) -> dict:
    dati = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(url, data=dati, method=metodo, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": AGENTE,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as risposta:
        return json.loads(risposta.read() or b"{}")


def _spiega(e: urllib.error.HTTPError, azione: str) -> ErroreGitHub:
    motivi = {
        401: "token non valido o scaduto: generane uno nuovo e riesegui installa.sh",
        403: "il token non ha il permesso necessario (Contents: Read and write su questo repository)",
        404: "repository non trovato, oppure il token non è abilitato a questo repository",
    }
    return ErroreGitHub(f"{azione}: HTTP {e.code} — {motivi.get(e.code, e.reason)}")


def _url(repo: str, percorso: str) -> str:
    return f"{API}/repos/{repo}/contents/{quote(percorso)}"


def leggi(repo: str, percorso: str, tok: str, ramo: str = "main") -> tuple[str | None, str | None]:
    """Restituisce (testo, sha) del file, oppure (None, None) se non esiste."""
    try:
        r = _chiama("GET", f"{_url(repo, percorso)}?ref={quote(ramo)}", tok)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # 404 vale sia "file assente" sia "repository invisibile": si distingue sotto
            try:
                _chiama("GET", f"{API}/repos/{repo}", tok)
            except urllib.error.HTTPError as e2:
                raise _spiega(e2, f"lettura di {repo}") from None
            return None, None
        raise _spiega(e, f"lettura di {percorso}") from None
    if r.get("encoding") != "base64" or "content" not in r:
        raise ErroreGitHub(f"lettura di {percorso}: formato della risposta inatteso")
    return base64.b64decode(r["content"]).decode("utf-8"), r["sha"]


def scrivi(repo: str, percorso: str, tok: str, testo: str, sha: str | None,
           messaggio: str, ramo: str = "main") -> str:
    """Sostituisce il file con un nuovo commit; restituisce lo sha del commit."""
    corpo = {
        "message": messaggio,
        "content": base64.b64encode(testo.encode("utf-8")).decode("ascii"),
        "branch": ramo,
    }
    if sha:
        corpo["sha"] = sha
    try:
        r = _chiama("PUT", _url(repo, percorso), tok, corpo)
    except urllib.error.HTTPError as e:
        # 409: sha superato; 422: file comparso dopo una lettura che lo dava assente
        if e.code in (409, 422):
            raise Conflitto(f"{percorso} è cambiato su GitHub durante l'aggiornamento") from None
        raise _spiega(e, f"scrittura di {percorso}") from None
    return r.get("commit", {}).get("sha", "")
