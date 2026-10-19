"""Genera le icone dell'app (una paletta Solari con il simbolo dell'euro).

Serve solo a chi modifica le icone; l'app non ne ha bisogno per funzionare.

    pip install pillow            # su Arch: sudo pacman -S python-pillow
    python3 strumenti/genera_icone.py percorso/BarlowCondensed-SemiBold.ttf

Il carattere Barlow Condensed (licenza OFL) si scarica da Google Fonts.
Autore: Biagio Raucci — Licenza MIT.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NOTTE = (11, 12, 13)
CASSA = (20, 21, 23)
ALTA = ((38, 39, 42), (31, 32, 34))
BASSA = ((27, 28, 30), (22, 23, 25))
FESSURA = (5, 5, 6)
PERNO = (59, 61, 66)
GESSO = (241, 238, 228)
SEGNALE = (247, 200, 115)

USCITA = Path(__file__).resolve().parent.parent / "icone"


def _sfumatura(img: Image.Image, riquadro, colori) -> None:
    x0, y0, x1, y1 = riquadro
    d = ImageDraw.Draw(img)
    (r0, g0, b0), (r1, g1, b1) = colori
    for y in range(y0, y1):
        t = (y - y0) / max(1, y1 - y0 - 1)
        d.line([(x0, y), (x1 - 1, y)], fill=(round(r0 + (r1 - r0) * t), round(g0 + (g1 - g0) * t), round(b0 + (b1 - b0) * t)))


def icona(lato: int, carattere: Path, proporzione: float, sfondo_pieno: bool) -> Image.Image:
    """proporzione: frazione del lato occupata dalla paletta (≤ 0.8 per le maskable)."""
    k = 4                                    # sovracampionamento per bordi puliti
    L = lato * k
    if sfondo_pieno:                         # maskable e iOS: quadrato pieno
        img = Image.new("RGBA", (L, L), NOTTE + (255,))
    else:                                    # "any": angoli trasparenti
        img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle([0, 0, L - 1, L - 1], radius=int(L * .2), fill=CASSA)
    d = ImageDraw.Draw(img)

    h = int(L * proporzione)
    w = int(h * .72)
    x0, y0 = (L - w) // 2, (L - h) // 2 + int(L * .03)
    r = int(w * .09)
    meta = h // 2
    fessura = max(k * 2, int(h * .018))

    alta = Image.new("RGB", (w, meta), ALTA[0])
    _sfumatura(alta, (0, 0, w, meta), ALTA)
    bassa = Image.new("RGB", (w, h - meta), BASSA[0])
    _sfumatura(bassa, (0, 0, w, h - meta), BASSA)
    maschera = Image.new("L", (w, h), 0)
    ImageDraw.Draw(maschera).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    paletta = Image.new("RGB", (w, h), FESSURA)
    paletta.paste(alta, (0, 0))
    paletta.paste(bassa, (0, meta))
    pd = ImageDraw.Draw(paletta)
    pd.rectangle([0, meta - fessura // 2, w, meta + fessura // 2], fill=FESSURA)

    font = ImageFont.truetype(str(carattere), int(h * .78))
    sx, sy, ex, ey = pd.textbbox((0, 0), "€", font=font)
    tx, ty = (w - (ex - sx)) // 2 - sx, (h - (ey - sy)) // 2 - sy
    testo = Image.new("L", (w, h), 0)
    ImageDraw.Draw(testo).text((tx, ty), "€", font=font, fill=255)
    # la fessura taglia anche il carattere, come sulle palette vere
    ImageDraw.Draw(testo).rectangle([0, meta - fessura // 2, w, meta + fessura // 2], fill=0)
    paletta.paste(Image.new("RGB", (w, h), GESSO), (0, 0), testo)
    img.paste(paletta, (x0, y0), maschera)

    # perni della cerniera e barra gialla dell'intestazione
    p = max(k * 2, int(w * .035))
    d.rectangle([x0 - p, y0 + meta - p * 2, x0 + p // 2, y0 + meta + p * 2], fill=PERNO)
    d.rectangle([x0 + w - p // 2, y0 + meta - p * 2, x0 + w + p, y0 + meta + p * 2], fill=PERNO)
    barra = int(h * .045)
    d.rectangle([x0, y0 - barra * 3, x0 + w, y0 - barra * 2], fill=SEGNALE)
    img = img.resize((lato, lato), Image.LANCZOS)
    return img if not sfondo_pieno else img.convert("RGB")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    carattere = Path(sys.argv[1])
    USCITA.mkdir(exist_ok=True)
    icona(192, carattere, .66, False).save(USCITA / "icona-192.png", optimize=True)
    icona(512, carattere, .66, False).save(USCITA / "icona-512.png", optimize=True)
    icona(512, carattere, .52, True).save(USCITA / "icona-maskable-512.png", optimize=True)
    icona(180, carattere, .66, True).save(USCITA / "apple-touch-icon.png", optimize=True)
    for f in sorted(USCITA.glob("*.png")):
        print(f"{f.name:28} {f.stat().st_size:>7} byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
