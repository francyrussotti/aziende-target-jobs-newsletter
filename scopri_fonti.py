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
I candidati dubbi (nome solo compatibile) vanno in "da_verificare" e non si usano.

Ogni run ha un tempo massimo (--minuti): si parte dalle aziende mai
controllate, poi da quelle controllate da più tempo, e si salva a intervalli.
Così la ricerca completa può richiedere più run senza perdere nulla.
Le fonti confermate restano finché non cambiano le regole (REGOLE).

Uso:
    python scopri_fonti.py              # tutte le aziende, entro 40 minuti
    python scopri_fonti.py --focus      # solo Parigi / Italia / open innovation / classe A
    python scopri_fonti.py --id novaspace --id euroquality
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import fonti as tf
import siti
from newsletter import AZIENDE_FILE, FONTI_FILE, FONTI_MANUALI_FILE, _leggi_json

SALVA_OGNI = 40   # aziende
# Versione delle regole di accettazione: se cambia, l'elenco riparte da zero.
# Con la stessa versione le fonti già confermate restano anche se un sito una
# volta non risponde (una fonte che smette di funzionare la segnala la newsletter).
REGOLE = 5


def salva(fonti, da_verificare, controllate, oggi):
    tmp = FONTI_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": oggi, "regole": REGOLE, "nota": "File generato da scopri_fonti.py: per "
                   "correggere o confermare una fonte usa dati/fonti_manuali.json. "
                   "'da_verificare' = candidati dubbi (nome solo compatibile), NON usati.",
                   "fonti": dict(sorted(fonti.items())),
                   "da_verificare": dict(sorted(da_verificare.items())),
                   "controllate": dict(sorted(controllate.items()))},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, FONTI_FILE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", action="store_true")
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--thread", type=int, default=16)
    ap.add_argument("--minuti", type=float, default=40)
    a = ap.parse_args()
    fine = time.monotonic() + a.minuti * 60

    aziende = _leggi_json(AZIENDE_FILE, {}).get("aziende", [])
    ids = {x["id"] for x in aziende}
    manuali = _leggi_json(FONTI_MANUALI_FILE, {})
    vecchio = _leggi_json(FONTI_FILE, {})
    if vecchio.get("regole") != REGOLE:
        print(f"Regole cambiate ({vecchio.get('regole')} → {REGOLE}): elenco fonti ricostruito da zero")
        vecchio = {}
    # Solo aziende in lista e senza decisione manuale (la scelta manuale vince)
    tenere = lambda k: k in ids and k not in manuali
    fonti = {k: v for k, v in vecchio.get("fonti", {}).items() if tenere(k)}
    controllate = {k: v for k, v in vecchio.get("controllate", {}).items() if tenere(k)}
    siti_uff = _leggi_json(siti.SITI_FILE, {})

    da_cercare = [x for x in aziende if x["id"] not in manuali]
    if a.id:
        da_cercare = [x for x in da_cercare if x["id"] in a.id]
    elif a.focus:
        da_cercare = [x for x in da_cercare if x.get("k") or x.get("o") or x.get("c") == "A"]
    # Prima le mai controllate, poi le controllate da più tempo; a parità, le prioritarie
    da_cercare.sort(key=lambda x: (controllate.get(x["id"], ""), not x.get("k"), -(x.get("s") or 0)))
    print(f"🔎 Cerco fonti per {len(da_cercare)} aziende (max {a.minuti:.0f} minuti)…")

    oggi = datetime.now().strftime("%Y-%m-%d")
    fatte = trovate_oggi = 0

    def uno(az):
        if time.monotonic() > fine:
            return az, None                       # tempo scaduto: resta per il prossimo run
        # 1) dal sito ufficiale (verificato per costruzione); 2) slug sui portali
        dal_sito = siti.trova_fonti_sito(siti_uff[az["id"]]) if az["id"] in siti_uff else []
        tipi_trovati = {f["tipo"] for f in dal_sito}
        return az, dal_sito + [f for f in tf.scopri(az)
                               if f["tipo"] not in tipi_trovati or "da_verificare" in f]

    da_verificare = {k: v for k, v in vecchio.get("da_verificare", {}).items() if tenere(k)}
    with ThreadPoolExecutor(max_workers=a.thread) as ex:
        for az, trovate in ex.map(uno, da_cercare):
            if trovate is None:
                continue
            fatte += 1
            controllate[az["id"]] = oggi
            buone = [f for f in trovate if "da_verificare" not in f]
            dubbie = [f for f in trovate if "da_verificare" in f]
            # Unione con le fonti già confermate con le stesse regole: un sito che
            # oggi non risponde non deve far sparire la sua fonte.
            prima = {tf.chiave_fonte(f) for f in fonti.get(az["id"], [])}
            unite = {tf.chiave_fonte(f): f for f in fonti.get(az["id"], [])}
            for f in buone:
                unite.setdefault(tf.chiave_fonte(f), {**f, "trovata": oggi})
            if unite:
                fonti[az["id"]] = list(unite.values())
            dubbie = [f for f in dubbie if tf.chiave_fonte(f) not in unite]
            if dubbie:
                da_verificare[az["id"]] = dubbie
            else:
                da_verificare.pop(az["id"], None)
            if set(unite) - prima:
                trovate_oggi += 1
                print(f"   ✅ {az['n']} [{az['id']}]: " + ", ".join(
                    f"{tf.chiave_fonte(f)} ({f.get('verifica', '')})" for f in buone), flush=True)
            for f in dubbie:
                print(f"   ❔ {az['n']} [{az['id']}]: {tf.chiave_fonte(f)} ({f['da_verificare']})", flush=True)
            if fatte % SALVA_OGNI == 0:
                salva(fonti, da_verificare, controllate, oggi)
                print(f"   … {fatte}/{len(da_cercare)} controllate", flush=True)

    salva(fonti, da_verificare, controllate, oggi)
    restano = len(da_cercare) - fatte
    print(f"\n💾 {fatte} aziende controllate, {trovate_oggi} con fonte nuova · "
          f"{len(fonti)} aziende con fonte in totale"
          + (f" · {restano} da controllare al prossimo run" if restano else ""))


if __name__ == "__main__":
    main()
