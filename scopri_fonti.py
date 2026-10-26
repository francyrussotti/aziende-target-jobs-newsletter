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
    python scopri_fonti.py --nuove      # solo le aziende mai controllate
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
REGOLE = 7


def salva(fonti, da_verificare, controllate, oggi, irraggiungibili=None):
    tmp = FONTI_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": oggi, "regole": REGOLE, "nota": "File generato da scopri_fonti.py: per "
                   "correggere o confermare una fonte usa dati/fonti_manuali.json. "
                   "'da_verificare' = candidati dubbi (nome solo compatibile), NON usati.",
                   "fonti": dict(sorted(fonti.items())),
                   "da_verificare": dict(sorted(da_verificare.items())),
                   "siti_irraggiungibili": dict(sorted((irraggiungibili or {}).items())),
                   "controllate": dict(sorted(controllate.items()))},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, FONTI_FILE)


def diagnosi(azienda, sito):
    """Stampa, passo per passo, cosa vede la ricerca per un'azienda (nessuna scrittura)."""
    from urllib.parse import urljoin
    print(f"\n■ {azienda['n']} [{azienda['id']}] · paesi {azienda.get('p')} · sito {sito or '—'}")
    if sito:
        try:
            html, fin = siti._html(sito, rapida=False)
            print(f"   home: ok → {fin} ({len(html)} caratteri)")
            portali, carriere = siti.link_carriere(html, fin)
            print(f"   portali linkati: {[tf.chiave_fonte(f) for f in portali] or 'nessuno'}")
            print(f"   link carriere scelto: {carriere or 'nessuno'}")
            candidate = [carriere] if carriere else [urljoin(fin, p) for p in siti.PERCORSI_COMUNI]
            for u in candidate:
                try:
                    h, f2 = siti._html(u)
                except tf.FonteErrore as e:
                    if carriere:
                        print(f"   {u}: errore {e}")
                    continue
                termini = sorted({m.group(1).lower() for m in siti.RE_LESSICO_LAVORO.finditer(
                    __import__("bs4").BeautifulSoup(h, "lxml").get_text(" ", strip=True))})
                print(f"   {u} → {f2}: carriere={bool(siti.RE_CARRIERE.search(f2))} "
                      f"articolo={siti.sembra_articolo(f2)} bacheca={siti.bacheca_di_rete(f2)} "
                      f"lessico={termini[:8]} portali={[tf.chiave_fonte(x) for x in siti.link_carriere(h, f2)[0]]}")
                print(f"      link annuncio estratti: {[o['titolo'][:50] for o in tf.estrai_link_annunci(h, f2)][:6]}")
        except tf.FonteErrore as e:
            print(f"   home: IRRAGGIUNGIBILE ({e})")
    tipi = tf.TIPI_SCOPERTA + (["wttj"] if "FR" in (azienda.get("p") or "").split(",") else [])
    for tipo in tipi:
        for slug in tf.slug_candidati(azienda["n"]):
            esito = tf._prova(tipo, slug, azienda)
            if esito:
                print(f"   slug {tipo}:{slug} → {esito.get('verifica') or esito.get('da_verificare')}")
    if "FR" in (azienda.get("p") or "").split(","):
        for slug in tf.slug_candidati(azienda["n"])[:2]:
            try:
                r = tf._get(f"https://www.welcometothejungle.com/fr/companies/{slug}", rapida=True,
                            headers={"Accept": "text/html"})
                print(f"   wttj {slug}: HTTP {r.status_code}")
            except tf.FonteErrore as e:
                print(f"   wttj {slug}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnosi", action="store_true", help="solo stampa, per gli --id indicati")
    ap.add_argument("--focus", action="store_true")
    ap.add_argument("--nuove", action="store_true", help="solo aziende mai controllate (es. appena entrate in lista)")
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--thread", type=int, default=16)
    ap.add_argument("--minuti", type=float, default=40)
    a = ap.parse_args()
    if a.diagnosi:
        az = {x["id"]: x for x in _leggi_json(AZIENDE_FILE, {}).get("aziende", [])}
        siti_uff = _leggi_json(siti.SITI_FILE, {})
        siti_uff.update({k: v["url"] for k, v in _leggi_json("dati/siti_manuali.json", {}).items()
                         if not k.startswith("_")})
        for i in a.id:
            if i in az:
                diagnosi(az[i], siti_uff.get(i))
        return
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
    # Correzioni a mano dei siti (domini vecchi in CORDIS)
    siti_uff.update({k: v["url"] for k, v in _leggi_json("dati/siti_manuali.json", {}).items()
                     if not k.startswith("_") and k in ids})

    da_cercare = [x for x in aziende if x["id"] not in manuali]
    if a.id:
        da_cercare = [x for x in da_cercare if x["id"] in a.id]
    elif a.nuove:
        da_cercare = [x for x in da_cercare if x["id"] not in controllate]
    elif a.focus:
        da_cercare = [x for x in da_cercare if x.get("k") or x.get("o") or x.get("c") == "A"]
    # Prima le mai controllate, poi le controllate da più tempo; a parità, le prioritarie
    da_cercare.sort(key=lambda x: (controllate.get(x["id"], ""), not x.get("k"), -(x.get("s") or 0)))
    print(f"🔎 Cerco fonti per {len(da_cercare)} aziende (max {a.minuti:.0f} minuti)…")
    if not da_cercare:
        return                                   # niente da fare: fonti.json non si tocca

    oggi = datetime.now().strftime("%Y-%m-%d")
    fatte = trovate_oggi = 0

    def uno(az):
        if time.monotonic() > fine:
            return az, None, None                 # tempo scaduto: resta per il prossimo run
        # 1) dal sito ufficiale (verificato per costruzione); 2) slug sui portali
        if az["id"] in siti_uff:
            dal_sito = siti.trova_fonti_sito(siti_uff[az["id"]])
            esito = "irraggiungibile" if dal_sito is None else ("con fonte" if dal_sito else "senza pagina carriere")
            dal_sito = dal_sito or []
        else:
            dal_sito, esito = [], None
        tipi_trovati = {f["tipo"] for f in dal_sito}
        return az, dal_sito + [f for f in tf.scopri(az)
                               if f["tipo"] not in tipi_trovati or "da_verificare" in f], esito

    da_verificare = {k: v for k, v in vecchio.get("da_verificare", {}).items() if tenere(k)}
    irraggiungibili = {k: v for k, v in vecchio.get("siti_irraggiungibili", {}).items() if tenere(k)}
    esiti_siti = {}
    with ThreadPoolExecutor(max_workers=a.thread) as ex:
        for az, trovate, esito in ex.map(uno, da_cercare):
            if trovate is None:
                continue
            if esito:
                esiti_siti[esito] = esiti_siti.get(esito, 0) + 1
                if esito == "irraggiungibile":
                    irraggiungibili[az["id"]] = siti_uff[az["id"]]
                else:
                    irraggiungibili.pop(az["id"], None)
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
                salva(fonti, da_verificare, controllate, oggi, irraggiungibili)
                print(f"   … {fatte}/{len(da_cercare)} controllate", flush=True)

    salva(fonti, da_verificare, controllate, oggi, irraggiungibili)
    restano = len(da_cercare) - fatte
    provati = sum(esiti_siti.values())
    if provati:
        print(f"\n🌐 Siti ufficiali provati: {provati} · raggiunti {provati - esiti_siti.get('irraggiungibile', 0)}"
              f" · con pagina carriere o portale {esiti_siti.get('con fonte', 0)}"
              f" · senza {esiti_siti.get('senza pagina carriere', 0)}"
              f" · irraggiungibili {esiti_siti.get('irraggiungibile', 0)} (elenco in fonti.json)")
    print(f"\n💾 {fatte} aziende controllate, {trovate_oggi} con fonte nuova · "
          f"{len(fonti)} aziende con fonte in totale"
          + (f" · {restano} da controllare al prossimo run" if restano else ""))


if __name__ == "__main__":
    main()
