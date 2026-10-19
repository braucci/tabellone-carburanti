"""Tabellone Carburanti — motore di acquisizione dei prezzi medi ufficiali MIMIT.

Il pacchetto è diviso secondo lo schema solutore / pre-post-processore:

* ``core.py``     funzioni pure (nessuna rete, nessun file): lettura della pagina,
                  storico, composizione del JSON e invarianti;
* ``aggiorna.py`` strato di I/O: rete (con rispetto di robots.txt), lettura e
                  scrittura atomica di ``data/prezzi.json``, riepilogo a video.

Autore: Biagio Raucci — Licenza MIT.
"""

__version__ = "1.1.0"
