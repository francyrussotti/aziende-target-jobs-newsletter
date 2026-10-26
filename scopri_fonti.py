#!/usr/bin/env python3
"""
Cerca, per ogni azienda della lista (dati/aziende.json), un portale di
selezione con API pubblica e lo salva in dati/fonti.json.

Per ogni azienda si provano alcuni "slug" ricavati dal nome su Greenhouse,
Lever, Workable, SmartRecruiters, Ashby, Recruitee e, per le aziende francesi,
Welcome to the Jungle. Una fonte si tiene SOLO se il nome dell'azienda
restituito dal portale (o citato negli annunci) corrisponde a quello in lista:
così non entrano annunci di aziende omonime.

Le aziende in dati/fonti_manuali.json non si cercano (vince la scelta manuale).
Le fonti trovate in passato restano finché non si trova qualcosa di diverso.

Uso:
    python scopri_fonti.py            # tutte le aziende
    python scopri_fonti.py --focus    # solo Parigi / Italia / open innovation / classe A
    python scopri_fonti.py --id novaspace --id euroquality
"""
import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import fonti as tf
from newsletter import AZIENDE_FILE, FONTI_FILE, FONTI_MANUALI_FILE, _leggi_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", action="store_true")
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--thread", type=int, default=12)
    a = ap.parse_args()

    aziende = _leggi_json(AZIENDE_FILE, {}).get("aziende", [])
    manuali = _leggi_json(FONTI_MANUALI_FILE, {})
    vecchio = _leggi_json(FONTI_FILE, {})
    fonti = {k: v for k, v in vecchio.get("fonti", {}).items()
             if k in {x["id"] for x in aziende}}           # solo aziende ancora in lista

    da_cercare = [x for x in aziende if x["id"] not in manuali]
    if a.id:
        da_cercare = [x for x in da_cercare if x["id"] in a.id]
    elif a.focus:
        da_cercare = [x for x in da_cercare if x.get("k") or x.get("o") or x.get("c") == "A"]
    print(f"🔎 Cerco fonti per {len(da_cercare)} aziende…")

    oggi = datetime.now().strftime("%Y-%m-%d")

    def uno(az):
        return az, tf.scopri(az)

    nuove = 0
    with ThreadPoolExecutor(max_workers=a.thread) as ex:
        for az, trovate in ex.map(uno, da_cercare):
            if not trovate:
                continue
            for f in trovate:
                f.setdefault("trovata", oggi)
            prima = {tf.chiave_fonte(f) for f in fonti.get(az["id"], [])}
            if {tf.chiave_fonte(f) for f in trovate} - prima:
                nuove += 1
                print(f"   ✅ {az['n']}: " + ", ".join(
                    f"{f['tipo']}:{f['slug']} ({f['verifica']})" for f in trovate))
            # Unione: una fonte trovata in passato non sparisce per un errore di rete
            unite = {tf.chiave_fonte(f): f for f in fonti.get(az["id"], [])}
            for f in trovate:
                unite.setdefault(tf.chiave_fonte(f), f)
            fonti[az["id"]] = list(unite.values())

    tmp = FONTI_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": oggi, "nota": "File generato da scopri_fonti.py: per "
                   "correggere una fonte usa dati/fonti_manuali.json",
                   "fonti": dict(sorted(fonti.items()))}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, FONTI_FILE)
    print(f"\n💾 {len(fonti)} aziende con fonte in {FONTI_FILE} ({nuove} aggiornate oggi)")


if __name__ == "__main__":
    main()
