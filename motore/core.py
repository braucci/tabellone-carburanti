"""Tabellone Carburanti — core: funzioni pure di lettura e composizione dei dati.

Nessuna funzione di questo modulo accede alla rete o al disco: ricevono testo
(o strutture dati) e restituiscono strutture dati. Questo le rende verificabili
in isolamento, come un solutore che si collauda su casi noti prima di essere
accoppiato al pre/post-processore.

Fonti
-----
1. Il file ufficiale ``MediaNazionaleAutostradale.csv`` ("Media prezzi alle 8"),
   con la data esplicita della rilevazione: è la fonte principale.
2. La pagina "Prezzi medi dei carburanti - Autostrade", tabella
   ``TIPOLOGIA | EROGAZIONE | PREZZO MEDIO``: fonte di riserva.

Il tabellone riporta i valori così come sono pubblicati: nessun calcolo,
nessuna stima. L'erogazione (SELF o SERVITO) è letta dalla fonte, non presupposta.

Autore: Biagio Raucci — Licenza MIT.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Costanti di dominio
# ---------------------------------------------------------------------------

SCHEMA = 2

#: Carburanti del tabellone, nell'ordine della pagina ministeriale (lo stesso
#: previsto per i cartelloni dei distributori: gasolio, benzina, GPL, metano).
CARBURANTI: tuple[str, ...] = ("gasolio", "benzina", "gpl", "metano")

NOMI = {"gasolio": "GASOLIO", "benzina": "BENZINA", "gpl": "GPL", "metano": "METANO"}

#: Unità di misura dei prezzi secondo i metadati MIMIT: litro in tutti i casi
#: tranne il metano, venduto a chilogrammo.
UNITA = {"gasolio": "€/l", "benzina": "€/l", "gpl": "€/l", "metano": "€/kg"}

EROGAZIONI = ("SELF", "SERVITO")

PREZZO_MIN = Decimal("0.3")  # filtro di plausibilità contro errori di lettura
PREZZO_MAX = Decimal("5.0")
GIORNI_STORICO = 400         # profondità dello storico conservato nel JSON
FINESTRA_DATA = 10           # giorni entro cui cercare la data nella pagina
MILLESIMO = Decimal("0.001")

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


# ---------------------------------------------------------------------------
# Utilità numeriche
# ---------------------------------------------------------------------------

def al_millesimo(x: Decimal | float | str) -> float:
    """Riporta un valore al millesimo con la regola commerciale (metà per eccesso)."""
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    return float(d.quantize(MILLESIMO, rounding=ROUND_HALF_UP))


def differenza(a: float, b: float) -> float:
    """a − b calcolata in decimale: in virgola mobile 2.297 − 2.298 non vale −0.001."""
    return al_millesimo(Decimal(str(a)) - Decimal(str(b)))


def leggi_prezzo(testo: str) -> Decimal | None:
    """Converte '2.297', '2,297', '1.900 €' in Decimal; None se non è un prezzo."""
    pulito = testo.strip().replace("€", "").replace("euro", "").strip()
    if not re.fullmatch(r"\d{1,2}[.,]\d{1,4}", pulito):
        return None
    try:
        return Decimal(pulito.replace(",", "."))
    except InvalidOperation:
        return None


def erogazione(testo: str) -> str | None:
    """'SELF', 'Self service', 'self-service' → 'SELF'; 'Servito' → 'SERVITO'."""
    t = " ".join(testo.lower().replace("-", " ").split())
    if t.startswith("self"):
        return "SELF"
    if t.startswith("servit"):
        return "SERVITO"
    return None


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_IT = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RE_TRATTINI = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")
_RE_ESTESA = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MESI) + r")\s+(\d{4})\b", re.IGNORECASE
)


def date_nel_testo(testo: str) -> list[date]:
    """Tutte le date riconoscibili in un testo (gg/mm/aaaa, gg-mm-aaaa, ISO, '19 ottobre 2026')."""
    trovate: list[date] = []
    for m in _RE_ISO.finditer(testo):
        _aggiungi(trovate, int(m[1]), int(m[2]), int(m[3]))
    for m in _RE_IT.finditer(testo):
        _aggiungi(trovate, int(m[3]), int(m[2]), int(m[1]))
    for m in _RE_TRATTINI.finditer(testo):
        _aggiungi(trovate, int(m[3]), int(m[2]), int(m[1]))
    for m in _RE_ESTESA.finditer(testo):
        _aggiungi(trovate, int(m[3]), MESI[m[2].lower()], int(m[1]))
    return trovate


def _aggiungi(lista: list[date], a: int, m: int, g: int) -> None:
    try:
        lista.append(date(a, m, g))
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Pagina ufficiale (HTML)
# ---------------------------------------------------------------------------

def decodifica(dati: bytes | str) -> str:
    if isinstance(dati, str):
        return dati
    for codifica in ("utf-8-sig", "cp1252"):
        try:
            return dati.decode(codifica)
        except UnicodeDecodeError:
            continue
    return dati.decode("latin-1")


class _LettoreTabelle(HTMLParser):
    """Raccoglie le righe <tr> come liste di testi di cella, più il testo
    complessivo della pagina (esclusi script e stili)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.righe: list[list[str]] = []
        self.testo: list[str] = []
        self._riga: list[str] | None = None
        self._cella: list[str] | None = None
        self._muto = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._muto += 1
        elif tag == "tr":
            self._riga = []
        elif tag in ("td", "th") and self._riga is not None:
            self._cella = []
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4"):
            self.testo.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._muto = max(0, self._muto - 1)
        elif tag in ("td", "th") and self._cella is not None:
            if self._riga is not None:
                self._riga.append(" ".join("".join(self._cella).split()))
            self._cella = None
        elif tag == "tr" and self._riga is not None:
            if self._riga:
                self.righe.append(self._riga)
            self._riga = None
        self.testo.append(" ")

    def handle_data(self, data):
        if self._muto:
            return
        if self._cella is not None:
            self._cella.append(data)
        self.testo.append(data)


@dataclass
class RisultatoUfficiale:
    data: date
    voci: dict[str, dict]     # carburante → {"erogazione": "SELF", "prezzo": 2.297}
    data_dedotta: bool


def _accetta(voci: dict, tipologia: str, testo_erogazione: str, testo_prezzo: str) -> None:
    """Registra una riga se ha un carburante noto (tipologia esatta), un'erogazione
    riconoscibile e un prezzo plausibile; a parità di carburante vale la prima."""
    carburante = tipologia.strip().lower()
    modo = erogazione(testo_erogazione)
    p = leggi_prezzo(testo_prezzo)
    if (carburante in CARBURANTI and carburante not in voci and modo
            and p is not None and PREZZO_MIN <= p <= PREZZO_MAX):
        voci[carburante] = {"erogazione": modo, "prezzo": al_millesimo(p)}


_RE_RIGA_TESTUALE = re.compile(
    r"\b(gasolio|benzina|gpl|metano)\b[\s|]*"
    r"(self(?:[\s-]*service)?|servito)[\s|]*(\d[.,]\d{3})\b",
    re.IGNORECASE,
)


def leggi_pagina_ufficiale(html: bytes | str, oggi: date) -> RisultatoUfficiale:
    """Estrae dalla pagina MIMIT le righe  TIPOLOGIA | EROGAZIONE | PREZZO MEDIO.

    Il parsing è indipendente dal markup: si esaminano tutte le righe di
    tabella e si accettano quelle con tipologia esattamente uguale a un
    carburante noto (sono quindi esclusi GNL, L-GNC e i carburanti speciali),
    un'erogazione riconoscibile e un prezzo plausibile. Se un carburante
    compare più volte vale la prima riga, come nell'ordine della pagina.
    In mancanza di tabelle si ripiega su un'espressione regolare sul testo.

    Data: la più recente data presente nel testo fra oggi−10 e oggi; se manca,
    si assume ``oggi`` (le medie sono calcolate sui prezzi delle 8:00 del
    giorno stesso) e lo si segnala con ``data_dedotta``.
    """
    lettore = _LettoreTabelle()
    lettore.feed(decodifica(html))
    lettore.close()

    voci: dict[str, dict] = {}
    for riga in lettore.righe:
        if len(riga) >= 3:
            _accetta(voci, riga[0], riga[1], riga[2])

    testo = " ".join("".join(lettore.testo).split())
    if not voci:
        for m in _RE_RIGA_TESTUALE.finditer(testo):
            _accetta(voci, m[1], m[2], m[3])

    candidati = [d for d in date_nel_testo(testo)
                 if oggi - timedelta(days=FINESTRA_DATA) <= d <= oggi]
    if candidati:
        return RisultatoUfficiale(max(candidati), voci, False)
    return RisultatoUfficiale(oggi, voci, True)


# ---------------------------------------------------------------------------
# CSV ufficiale ("Media prezzi alle 8")
# ---------------------------------------------------------------------------

def leggi_csv_ufficiale(dati: bytes | str, oggi: date) -> RisultatoUfficiale:
    """Legge il file MIMIT MediaNazionaleAutostradale.csv:

        Aggiornamento 19-10-2026
        TIPO;TIPOLOGIA;EROGAZIONE;PREZZO MEDIO
        AUTOSTRADALE;Gasolio;SELF;2.297
        ...

    Le colonne si individuano per nome, non per posizione; il separatore si
    deduce dall'intestazione. Se c'è la colonna TIPO, si accettano solo le
    righe AUTOSTRADALE. La data è quella della riga «Aggiornamento»; se manca,
    o fosse nel futuro, si assume oggi e lo si segnala con ``data_dedotta``.
    """
    righe = [r for r in decodifica(dati).splitlines() if r.strip()]
    data = None
    for riga in righe:
        if riga.strip().lower().startswith("aggiornamento"):
            trovate = date_nel_testo(riga)
            data = trovate[0] if trovate else None
            break
    i_testa = next((i for i, r in enumerate(righe) if "tipologia" in r.lower()), None)
    voci: dict[str, dict] = {}
    if i_testa is not None:
        testa = righe[i_testa]
        sep = max(";|,\t", key=testa.count)
        colonne = [re.sub(r"\s+", "", c).lower() for c in next(csv.reader([testa], delimiter=sep))]
        try:
            i_tip, i_ero, i_prezzo = (colonne.index(n) for n in ("tipologia", "erogazione", "prezzomedio"))
        except ValueError:
            raise ValueError(f"intestazione del CSV inattesa: {testa!r}") from None
        i_tipo = colonne.index("tipo") if "tipo" in colonne else None
        for campi in csv.reader(righe[i_testa + 1:], delimiter=sep):
            if len(campi) <= max(i_tip, i_ero, i_prezzo):
                continue
            if i_tipo is not None and campi[i_tipo].strip().lower() != "autostradale":
                continue
            _accetta(voci, campi[i_tip], campi[i_ero], campi[i_prezzo])
    if data is not None and data <= oggi:
        return RisultatoUfficiale(data, voci, False)
    return RisultatoUfficiale(oggi, voci, True)


# ---------------------------------------------------------------------------
# Storico
# ---------------------------------------------------------------------------

def integra(storico: dict, giorno: date, voci: dict[str, dict]) -> dict:
    """Registra le voci di un giorno (sostituendo quelle già presenti).
    Operazione idempotente: integrare due volte gli stessi dati non cambia nulla."""
    for carburante, voce in voci.items():
        if carburante not in CARBURANTI:
            raise ValueError(f"carburante sconosciuto: {carburante}")
        storico.setdefault(giorno.isoformat(), {})[carburante] = {
            "erogazione": voce["erogazione"],
            "prezzo": voce["prezzo"],
        }
    return storico


def ultimo_giorno(storico: dict, prima_di: date | None = None) -> str | None:
    giorni = [g for g in storico if prima_di is None or g < prima_di.isoformat()]
    return max(giorni) if giorni else None


def pagina_invariata(storico: dict, ris: RisultatoUfficiale) -> str | None:
    """Riconosce una pagina non ancora aggiornata.

    Se la pagina non riporta una data (``data_dedotta``) e TUTTE le voci sono
    identiche, al millesimo, a quelle dell'ultimo giorno registrato, è molto
    più probabile che il Ministero non abbia ancora pubblicato i dati del
    giorno che non che quattro medie su centinaia di impianti siano rimaste
    tutte ferme. In tal caso si restituisce il giorno dell'ultima
    registrazione, e il nuovo giorno non viene scritto.
    """
    if not ris.data_dedotta or not ris.voci:
        return None
    precedente = ultimo_giorno(storico, prima_di=ris.data)
    if precedente is None:
        return None
    if all(storico[precedente].get(c) == v for c, v in ris.voci.items()):
        return precedente
    return None


def pota(storico: dict, oggi: date, giorni: int = GIORNI_STORICO) -> dict:
    soglia = (oggi - timedelta(days=giorni)).isoformat()
    return {g: storico[g] for g in sorted(storico) if g >= soglia}


def costruisci_tabellone(storico: dict) -> list[dict]:
    """Una riga per carburante: il valore più recente pubblicato.

    La variazione si calcola rispetto alla rilevazione precedente dello stesso
    carburante con la stessa erogazione: un passaggio da self a servito non è
    una variazione di prezzo.
    """
    giorni = sorted(storico, reverse=True)
    righe = []
    for carburante in CARBURANTI:
        riga = {
            "chiave": carburante,
            "carburante": NOMI[carburante],
            "unita": UNITA[carburante],
            "erogazione": None,
            "prezzo": None,
            "data": None,
            "variazione": None,
            "data_precedente": None,
        }
        g = next((g for g in giorni if carburante in storico[g]), None)
        if g:
            voce = storico[g][carburante]
            riga.update(erogazione=voce["erogazione"], prezzo=voce["prezzo"], data=g)
            for g2 in giorni:
                prec = storico[g2].get(carburante)
                if g2 < g and prec:
                    if prec["erogazione"] == voce["erogazione"]:
                        riga["variazione"] = differenza(voce["prezzo"], prec["prezzo"])
                        riga["data_precedente"] = g2
                    break
        righe.append(riga)
    return righe


# ---------------------------------------------------------------------------
# Composizione del JSON e invarianti
# ---------------------------------------------------------------------------

def componi(storico: dict, fonte: dict, generato_il: datetime, versione: str) -> dict:
    tabellone = costruisci_tabellone(storico)
    date_righe = [r["data"] for r in tabellone if r["data"]]
    return {
        "schema": SCHEMA,
        "app": "tabellone-carburanti",
        "versione": versione,
        "generato_il": generato_il.isoformat(timespec="seconds"),
        "rete": "Autostradale",
        "fonte": fonte,
        "rilevazione": max(date_righe) if date_righe else None,
        "tabellone": tabellone,
        "storico": {g: storico[g] for g in sorted(storico)},
    }


def contenuto_equivalente(a: dict | None, b: dict | None) -> bool:
    """Vero se due JSON differiscono solo per l'istante di generazione e per
    l'esito della fonte: in tal caso non serve riscrivere il file."""
    if a is None or b is None:
        return False
    chiavi = ("schema", "versione", "rilevazione", "tabellone", "storico")
    return all(a.get(k) == b.get(k) for k in chiavi)


def controlla_invarianti(dati: dict) -> None:
    """Asserzioni sul JSON prima della scrittura: se una fallisce, il file
    precedente resta intatto (meglio un dato vecchio che un dato sbagliato)."""
    assert dati["schema"] == SCHEMA, "schema inatteso"
    righe = dati["tabellone"]
    assert [r["chiave"] for r in righe] == list(CARBURANTI), "righe del tabellone fuori ordine"
    generato = datetime.fromisoformat(dati["generato_il"]).date()
    storico = dati["storico"]
    assert list(storico) == sorted(storico), "storico non ordinato"
    for g, voci in storico.items():
        date.fromisoformat(g)
        for carburante, voce in voci.items():
            assert carburante in CARBURANTI, f"carburante estraneo: {carburante}"
            assert voce["erogazione"] in EROGAZIONI, f"erogazione estranea: {voce}"
            assert float(PREZZO_MIN) <= voce["prezzo"] <= float(PREZZO_MAX), \
                f"prezzo implausibile {voce['prezzo']} ({g}, {carburante})"
    for r in righe:
        assert r["unita"] == UNITA[r["chiave"]]
        if r["prezzo"] is None:
            assert r["data"] is None and r["variazione"] is None
            continue
        assert date.fromisoformat(r["data"]) <= generato, f"data futura per {r['chiave']}"
        assert storico[r["data"]][r["chiave"]] == {"erogazione": r["erogazione"], "prezzo": r["prezzo"]}
        if r["variazione"] is not None:
            # Chiusura del bilancio: prezzo − variazione = prezzo precedente.
            prec = storico[r["data_precedente"]][r["chiave"]]
            assert prec["erogazione"] == r["erogazione"]
            assert differenza(r["prezzo"], r["variazione"]) == prec["prezzo"]
    assert dati["rilevazione"] == max((r["data"] for r in righe if r["data"]), default=None)
