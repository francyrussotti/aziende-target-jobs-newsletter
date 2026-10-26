#!/usr/bin/env python3
"""
Importa la lista "Aziende Target Europa" in dati/aziende.json.

La lista nasce dal progetto aziende-target-europa (CORDIS + aziende open
innovation curate) e vive nella pagina artifact su claude.ai. La pagina
contiene i dati in <script type="application/json" id="dati">.

Uso:
    python importa_aziende.py --html pagina.html
    python importa_aziende.py --html page.html   # output di build_page.py

La newsletter considera SOLO le aziende di questo file.
"""
import argparse
import json
import re
import sys

OUT = "dati/aziende.json"
CAMPI = ("id", "n", "p", "k", "c", "l", "s", "o", "np")


def leggi_pagina(testo: str) -> dict:
    m = re.search(r'<script type="application/json" id="dati">(.*?)</script>', testo, re.S)
    if not m:
        raise ValueError("blocco dati non trovato nella pagina")
    return json.loads(m.group(1).replace("<\\/", "</"))


MAX_USCITE = 0.2   # oltre il 20% di aziende sparite la pagina è probabilmente rotta


def differenze(prima: dict, aziende: list):
    """ID nuovi e ID usciti rispetto all'elenco precedente."""
    dopo = {a["id"] for a in aziende}
    return sorted(dopo - set(prima)), sorted(set(prima) - dopo)


def compatta(aziende: list) -> list:
    out = []
    for a in aziende:
        if not a.get("id") or not a.get("n"):
            continue
        out.append({k: a.get(k) for k in CAMPI})
    # Ordine stabile (per punteggio, poi nome): diff git leggibili
    return sorted(out, key=lambda a: (-(a.get("s") or 0), a["n"].lower()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="pagina HTML con il blocco dati")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--forza", action="store_true", help="scrivi anche se sparisce molta parte della lista")
    a = ap.parse_args()
    dati = leggi_pagina(open(a.html, encoding="utf-8").read())
    aziende = compatta(dati.get("aziende", []))
    if len(aziende) < 50:
        sys.exit(f"Solo {len(aziende)} aziende: la pagina sembra incompleta, file non scritto")
    try:
        prima = {x["id"]: x["n"] for x in json.load(open(a.out, encoding="utf-8")).get("aziende", [])}
    except (OSError, ValueError):
        prima = {}
    nuove, uscite = differenze(prima, aziende)
    for i in nuove:
        print(f"   + {i}")
    for i in uscite:
        print(f"   - {i} ({prima[i]})")
    print(f"Aziende nuove: {len(nuove)} · uscite: {len(uscite)}")
    if prima and len(uscite) > MAX_USCITE * len(prima) and not a.forza:
        sys.exit(f"Uscirebbero {len(uscite)} aziende su {len(prima)}: pagina sospetta, file non scritto "
                 "(usa --forza se è giusto)")
    with open(a.out, "w", encoding="utf-8") as f:
        # Una riga per azienda: diff git leggibili quando la lista cambia
        f.write('{"generato": %s, "aziende": [\n' % json.dumps(dati.get("generato")))
        f.write(",\n".join(json.dumps(x, ensure_ascii=False) for x in aziende))
        f.write("\n]}\n")
    print(f"{len(aziende)} aziende → {a.out} (lista del {dati.get('generato')})")


if __name__ == "__main__":
    main()
