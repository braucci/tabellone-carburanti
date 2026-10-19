"""Prove del motore — si eseguono senza rete e senza dipendenze esterne.

    python3 -m unittest discover -s motore -t . -p 'test_*.py' -v

Il campione ``motore/campioni/pagina_autostrade.html`` ricalca la tabella
pubblicata dal MIMIT il 19/10/2026: è un caso con soluzione nota, come il
profilo di riferimento con cui si collauda un solutore.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__, aggiorna, core

CAMPIONI = Path(__file__).parent / "campioni"
RADICE = Path(__file__).parent.parent
PAGINA = CAMPIONI / "pagina_autostrade.html"
OGGI = date(2026, 10, 19)
ROMA = ZoneInfo("Europe/Rome")

ATTESE = {
    "gasolio": {"erogazione": "SELF", "prezzo": 2.297},
    "benzina": {"erogazione": "SELF", "prezzo": 2.048},
    "gpl": {"erogazione": "SERVITO", "prezzo": 0.901},
    "metano": {"erogazione": "SERVITO", "prezzo": 1.9},
}


class Numeri(unittest.TestCase):
    def test_differenza_esatta(self):
        # In virgola mobile 2.297 − 2.298 vale −0.0009999999999998899.
        self.assertNotEqual(2.297 - 2.298, -0.001)
        self.assertEqual(core.differenza(2.297, 2.298), -0.001)

    def test_prezzi(self):
        self.assertEqual(str(core.leggi_prezzo("2,297")), "2.297")
        self.assertEqual(str(core.leggi_prezzo(" 1.900 € ")), "1.900")
        self.assertIsNone(core.leggi_prezzo("SELF"))
        self.assertIsNone(core.leggi_prezzo("2026"))

    def test_erogazione(self):
        self.assertEqual(core.erogazione("SELF"), "SELF")
        self.assertEqual(core.erogazione("Self-service"), "SELF")
        self.assertEqual(core.erogazione("servito"), "SERVITO")
        self.assertIsNone(core.erogazione("PREZZO MEDIO"))


class PaginaUfficiale(unittest.TestCase):
    def test_tabella_come_sul_sito(self):
        r = core.leggi_pagina_ufficiale(PAGINA.read_bytes(), OGGI)
        self.assertEqual(r.voci, ATTESE)
        self.assertEqual(list(r.voci), list(core.CARBURANTI))     # ordine della pagina

    def test_data_assente_si_assume_oggi(self):
        # Le date 01/10/2026 (nello script), 31 marzo 2023 e 12/02/2026 non contano.
        r = core.leggi_pagina_ufficiale(PAGINA.read_bytes(), OGGI)
        self.assertEqual(r.data, OGGI)
        self.assertTrue(r.data_dedotta)

    def test_data_presente(self):
        html = PAGINA.read_text(encoding="utf-8").replace(
            "<h2>Media", "<p>Prezzi medi del 18/10/2026</p><h2>Media")
        r = core.leggi_pagina_ufficiale(html, OGGI)
        self.assertEqual(r.data, date(2026, 10, 18))
        self.assertFalse(r.data_dedotta)

    def test_script_ignorati(self):
        r = core.leggi_pagina_ufficiale(PAGINA.read_bytes(), OGGI)
        self.assertNotIn(9.999, [v["prezzo"] for v in r.voci.values()])

    def test_ripiego_testuale(self):
        html = ("<p>Gasolio | SELF | 2,300</p><p>Benzina Self service 2,051</p>"
                "<p>GPL SERVITO 0,900</p><p>19 ottobre 2026</p>")
        r = core.leggi_pagina_ufficiale(html, OGGI)
        self.assertEqual(r.voci, {
            "gasolio": {"erogazione": "SELF", "prezzo": 2.3},
            "benzina": {"erogazione": "SELF", "prezzo": 2.051},
            "gpl": {"erogazione": "SERVITO", "prezzo": 0.9},
        })
        self.assertFalse(r.data_dedotta)

    def test_esclusioni(self):
        html = ("<table><tr><td>Benzina speciale</td><td>SELF</td><td>2.400</td></tr>"
                "<tr><td>GNL</td><td>SERVITO</td><td>1.950</td></tr>"
                "<tr><td>Gasolio</td><td>SELF</td><td>12.297</td></tr>"
                "<tr><td>Metano</td><td>ALTRO</td><td>1.900</td></tr></table>")
        self.assertEqual(core.leggi_pagina_ufficiale(html, OGGI).voci, {})

    def test_prima_riga_vince(self):
        html = ("<table><tr><td>Gasolio</td><td>SELF</td><td>2.297</td></tr>"
                "<tr><td>Gasolio</td><td>SERVITO</td><td>2.450</td></tr></table>")
        self.assertEqual(core.leggi_pagina_ufficiale(html, OGGI).voci,
                         {"gasolio": {"erogazione": "SELF", "prezzo": 2.297}})


def _storico() -> dict:
    s: dict = {}
    core.integra(s, date(2026, 10, 18), {
        "gasolio": {"erogazione": "SELF", "prezzo": 2.298},
        "gpl": {"erogazione": "SELF", "prezzo": 0.880},       # erogazione diversa
    })
    core.integra(s, date(2026, 10, 19), ATTESE)
    return s


class Storico(unittest.TestCase):
    def test_idempotenza_e_andata_ritorno(self):
        a, b = _storico(), _storico()
        core.integra(b, date(2026, 10, 19), ATTESE)
        self.assertEqual(a, b)
        self.assertEqual(json.loads(json.dumps(a)), a)

    def test_tabellone(self):
        righe = {r["chiave"]: r for r in core.costruisci_tabellone(_storico())}
        g = righe["gasolio"]
        self.assertEqual((g["prezzo"], g["erogazione"], g["unita"], g["data"]),
                         (2.297, "SELF", "€/l", "2026-10-19"))
        self.assertEqual((g["variazione"], g["data_precedente"]), (-0.001, "2026-10-18"))
        # GPL: il 18/10 era SELF, il 19/10 SERVITO → nessuna variazione.
        self.assertIsNone(righe["gpl"]["variazione"])
        self.assertEqual(righe["metano"]["unita"], "€/kg")
        self.assertIsNone(righe["benzina"]["variazione"])     # nessun dato precedente

    def test_pagina_non_aggiornata(self):
        s = _storico()
        ieri = core.leggi_pagina_ufficiale(PAGINA.read_bytes(), OGGI)
        domani = core.RisultatoUfficiale(date(2026, 10, 20), ieri.voci, data_dedotta=True)
        self.assertEqual(core.pagina_invariata(s, domani), "2026-10-19")
        # Basta un valore diverso, o una data scritta nella pagina, per accettarla.
        cambiata = dict(ieri.voci, gasolio={"erogazione": "SELF", "prezzo": 2.301})
        self.assertIsNone(core.pagina_invariata(s, core.RisultatoUfficiale(date(2026, 10, 20), cambiata, True)))
        self.assertIsNone(core.pagina_invariata(s, core.RisultatoUfficiale(date(2026, 10, 20), ieri.voci, False)))

    def test_potatura(self):
        s = _storico()
        core.integra(s, date(2025, 1, 1), {"benzina": {"erogazione": "SELF", "prezzo": 1.8}})
        self.assertNotIn("2025-01-01", core.pota(s, OGGI, giorni=400))
        self.assertIn("2026-10-18", core.pota(s, OGGI, giorni=400))

    def test_invarianti(self):
        dati = core.componi(_storico(), {}, datetime(2026, 10, 19, 10, 47, tzinfo=ROMA), "x")
        core.controlla_invarianti(dati)
        self.assertEqual(dati["rilevazione"], "2026-10-19")
        dati["tabellone"][0]["variazione"] = -0.002          # bilancio non chiuso
        with self.assertRaises(AssertionError):
            core.controlla_invarianti(dati)


class Robots(unittest.TestCase):
    """Comportamento RFC 9309 simulato, senza rete."""

    def _con(self, effetto):
        originale = aggiorna._richiesta

        def finto(url, timeout=60):
            if isinstance(effetto, Exception):
                raise effetto
            return effetto.encode()

        aggiorna._richiesta = finto
        aggiorna._robots.clear()
        self.addCleanup(setattr, aggiorna, "_richiesta", originale)
        self.addCleanup(aggiorna._robots.clear)

    def test_regole(self):
        self._con("User-agent: *\nDisallow: /it/prezzo-medio-carburanti/\n")
        self.assertFalse(aggiorna.consentito(aggiorna.URL_PAGINA))
        self.assertTrue(aggiorna.consentito("https://www.mimit.gov.it/it/altro"))

    def test_robots_assente_consente(self):
        self._con(urllib.error.HTTPError("u", 404, "Not Found", {}, None))
        self.assertTrue(aggiorna.consentito(aggiorna.URL_PAGINA))

    def test_robots_irraggiungibile_vieta(self):
        self._con(urllib.error.HTTPError("u", 503, "Unavailable", {}, None))
        self.assertFalse(aggiorna.consentito(aggiorna.URL_PAGINA))
        with self.assertRaisesRegex(aggiorna.Vietato, r"irraggiungibile \(HTTP 503\).*RFC 9309"):
            aggiorna.scarica(aggiorna.URL_PAGINA)

    def test_log_mostra_la_regola(self):
        """Con un divieto esplicito il log riporta lo stato e le direttive, non i commenti."""
        self._con("# commento da non mostrare\nUser-agent: *\nDisallow: /it/  # area riservata\n")
        buf = io.StringIO()
        with redirect_stdout(buf), tempfile.TemporaryDirectory() as cartella:
            codice = aggiorna.main(["--json", str(Path(cartella) / "p.json"), "--oggi", OGGI.isoformat()])
        testo = buf.getvalue()
        self.assertEqual(codice, 1)
        self.assertIn("robots.txt non consente", testo)
        self.assertIn("robots.txt: letto (HTTP 200)", testo)
        self.assertIn("     User-agent: *\n     Disallow: /it/\n", testo)
        self.assertNotIn("commento", testo)


class EndToEnd(unittest.TestCase):
    def _esegui(self, uscita: Path, oggi: date) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            codice = aggiorna.main(["--json", str(uscita), "--pagina", str(PAGINA),
                                    "--oggi", oggi.isoformat()])
        return codice, buf.getvalue()

    def test_tre_esecuzioni(self):
        with tempfile.TemporaryDirectory() as cartella:
            uscita = Path(cartella) / "data" / "prezzi.json"
            # 1) primo giorno: file scritto con i quattro valori della pagina
            codice, _ = self._esegui(uscita, OGGI)
            self.assertEqual(codice, 0)
            primo = uscita.read_text(encoding="utf-8")
            dati = json.loads(primo)
            core.controlla_invarianti(dati)
            self.assertEqual({r["chiave"]: {"erogazione": r["erogazione"], "prezzo": r["prezzo"]}
                              for r in dati["tabellone"]}, ATTESE)
            # 2) stesso giorno, stessa pagina: file identico, nessun commit
            codice, testo = self._esegui(uscita, OGGI)
            self.assertEqual(codice, 0)
            self.assertIn("file invariato", testo)
            self.assertEqual(uscita.read_text(encoding="utf-8"), primo)
            # 3) giorno dopo, pagina non ancora aggiornata: nessun giorno nuovo
            codice, testo = self._esegui(uscita, date(2026, 10, 20))
            self.assertEqual(codice, 0)
            self.assertIn("non ancora aggiornata", testo)
            self.assertNotIn("2026-10-20", json.loads(uscita.read_text(encoding="utf-8"))["storico"])


class Versioni(unittest.TestCase):
    def test_versione_unica(self):
        """La stessa versione in pyproject, pacchetto, pagina e service worker."""
        fonti = {
            "pyproject.toml": r'^version = "([^"]+)"',
            "index.html": r"const VERSIONE = '([^']+)'",
            "sw.js": r"const VERSIONE = '([^']+)'",
        }
        for nome, modello in fonti.items():
            percorso = RADICE / nome
            if not percorso.exists():
                self.skipTest(f"{nome} assente")
            m = re.search(modello, percorso.read_text(encoding="utf-8"), re.MULTILINE)
            self.assertIsNotNone(m, nome)
            self.assertEqual(m[1], __version__, nome)


if __name__ == "__main__":
    unittest.main()
