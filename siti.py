#!/usr/bin/env python3
"""
Siti ufficiali delle aziende della lista e loro pagine "carriere".

1) `python siti.py` scarica i dati CORDIS (gli stessi da cui nasce la lista,
   ~37 MB) e salva in dati/siti.json il sito web dichiarato da ogni azienda
   (campo organizationURL), con gli stessi ID di dati/aziende.json.
2) `trova_fonti_sito(url)` apre la home dell'azienda e cerca:
   - link a un portale di selezione (Lever, Personio, Welcome to the Jungle…):
     sono verificati per costruzione, perché li linka il sito ufficiale;
   - altrimenti la pagina "carriere / lavora con noi / recrutement".
"""
import csv
import io
import json
import re
import sys
import urllib.request
import zipfile
from collections import Counter
from urllib.parse import urljoin, urlparse

import fonti as tf

CORDIS_URL = "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip"
SITI_FILE = "dati/siti.json"

# --- Stessa normalizzazione del progetto aziende-target-europa ---------------
# (cordis_discovery.normalizza + build_page.slug): serve a ritrovare gli ID.
RE_SUFFISSI = re.compile(
    r"\b(S\.?R\.?L\.?|S\.?P\.?A\.?|GMBH|G\.?M\.?B\.?H\.?|SAS|SA|SL|S\.?L\.?|SARL|BV|B\.?V\.?|AB|AS|LDA|UNIPESSOAL|"
    r"LIMITED|LTD|PC|OY|NV|N\.?V\.?|ASBL|EESV|SRO|AE|EOOD|IKE|APS|AG|KG|CO|UG|SPOL|S\.?R\.?O\.?|AB|UAB|SIA)\b\.?",
    re.I)


def normalizza(nome):
    n = re.sub(r"[^\w\s&+/-]", " ", str(nome).upper())
    n = RE_SUFFISSI.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def slug(brand):
    s = re.sub(r"[^a-z0-9]+", "-", str(brand).lower()).strip("-")
    return s[:120] or "azienda"


def pulisci_url(u):
    u = (u or "").strip()
    if not u or " " in u or "." not in u:
        return ""
    if not re.match(r"https?://", u, re.I):
        u = "https://" + u
    p = urlparse(u)
    if not p.netloc or any(x in p.netloc for x in ("linkedin.", "facebook.", "twitter.", "cordis.")):
        return ""
    return f"{p.scheme.lower()}://{p.netloc.lower()}/"


def siti_da_cordis(organization_csv_testo, ids):
    """{id azienda: url} scegliendo l'URL più dichiarato per ogni azienda."""
    conteggi = {}
    for r in csv.DictReader(io.StringIO(organization_csv_testo), delimiter=";"):
        i = slug(normalizza(r.get("name", "")))
        if i not in ids:
            continue
        u = pulisci_url(r.get("organizationURL"))
        if u:
            conteggi.setdefault(i, Counter())[u] += 1
    return {i: c.most_common(1)[0][0] for i, c in conteggi.items()}


def scarica_organization_csv():
    with urllib.request.urlopen(CORDIS_URL, timeout=300) as r:
        dati = r.read()
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        nome = next(n for n in z.namelist() if n.endswith("organization.csv"))
        return z.read(nome).decode("utf-8", errors="replace")


# --- Dal sito ufficiale alle fonti -------------------------------------------

def fonte_da_url(url):
    """Fonte per un link a un portale di selezione, o None."""
    p = urlparse(url)
    host, parti = p.netloc.lower(), [x for x in p.path.split("/") if x]
    primo = parti[0] if parti else ""
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and primo:
        f = {"tipo": "lever", "slug": primo}
        if ".eu." in host:
            f["eu"] = True
        return f
    if host.endswith("greenhouse.io") and host.startswith(("boards.", "job-boards.")) and ".eu." not in host:
        if primo and primo != "embed":
            return {"tipo": "greenhouse", "slug": primo}
        m = re.search(r"for=([\w-]+)", p.query)
        return {"tipo": "greenhouse", "slug": m.group(1)} if m else None
    if host == "apply.workable.com" and primo and primo not in ("j", "api"):
        return {"tipo": "workable", "slug": primo}
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and primo:
        return {"tipo": "smartrecruiters", "slug": primo}
    if host == "jobs.ashbyhq.com" and primo:
        return {"tipo": "ashby", "slug": primo}
    m = re.match(r"^([\w-]+)\.recruitee\.com$", host)
    if m and m.group(1) not in ("www", "app"):
        return {"tipo": "recruitee", "slug": m.group(1)}
    m = re.match(r"^([\w-]+)\.(jobs\.personio\.(?:de|com))$", host)
    if m:
        return {"tipo": "personio", "slug": m.group(1), "dominio": m.group(2)}
    if host.endswith("welcometothejungle.com"):
        m = re.search(r"/companies/([\w-]+)", p.path)
        return {"tipo": "wttj", "slug": m.group(1)} if m else None
    if host.endswith("myworkdayjobs.com") and parti:
        sito = [x for x in parti if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", x)][:1]
        lingua = [x for x in parti[:1] if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", x)]
        if sito:
            return {"tipo": "workday", "url": f"https://{host}/" + "/".join(lingua + sito)}
    # Pagine aziendali su altri portali: solo con il sottodominio dell'azienda
    # (www.teamtailor.com/jobs è il sito di Teamtailor, non di un cliente)
    m = re.match(r"^([\w-]+)\.(teamtailor\.com|bamboohr\.com|factorialhr\.\w+)$", host)
    if m and m.group(1) not in ("www", "app", "career", "careers", "api"):
        return {"tipo": "pagina", "url": f"https://{host}/" + ("jobs" if "teamtailor" in host else "")}
    return None


# Link alla pagina "carriere". Niente "opportunities"/"talent" da soli: nei siti
# di consulenza sui bandi UE "funding opportunities" è la pagina dei bandi.
# Link alla pagina "carriere". Niente "opportunities"/"talent"/"join us" da soli:
# nei siti di consulenza sui bandi UE "funding opportunities" sono i bandi e
# nelle associazioni "join us" è l'adesione alla rete.
RE_CARRIERE = re.compile(
    r"\b(careers?|jobs?|job[- ]opportunities|carri[eè]res?|lavora[- ]con[- ]noi|work[- ]with[- ]us|"
    r"join[- ]the[- ]team|join[- ]our[- ]team|nous[- ]rejoindre|rejoignez[- ]nous|recrutement|"
    r"on[- ]recrute|nous[- ]recrutons|offres[- ]d.emploi|emplois?|vacanc(y|ies)|posizioni[- ]aperte|"
    r"offerte[- ]di[- ]lavoro|we.?re[- ]hiring|karriere|stellenangebote|trabaja[- ]con[- ]nosotros|"
    r"empleo|lavora[- ]con[- ]us)\b", re.I)
# Una vera pagina carriere parla di lavoro: almeno 2 di questi termini diversi
RE_LESSICO_LAVORO = re.compile(
    r"\b(cdi|cdd|stage|stagiaire|internship|full[- ]time|part[- ]time|apply|postuler|candidat\w*|"
    r"job (?:offer|opening|description)s?|open positions?|vacanc(?:y|ies)|posizion[ei] apert\w*|"
    r"offerte di lavoro|curriculum|\bcv\b|recrutement|recrutons|we are hiring|hiring|offres? d.emploi|"
    r"lavora con noi|stellenangebote|bewerb\w*|empleo|ofertas? de empleo|tirocini\w*|"
    r"contrat|contratto|contract type|salary|salaire|retribuzione)\b", re.I)


def sembra_pagina_lavoro(html):
    from bs4 import BeautifulSoup
    testo = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return len({m.group(1).lower() for m in RE_LESSICO_LAVORO.finditer(testo)}) >= 2


def sembra_articolo(url):
    """/join-us-at-the-10th-insme-annual-meeting/ è un articolo, non la pagina carriere."""
    ultimo = [p for p in urlparse(url).path.split("/") if p][-1:] or [""]
    return len(re.split(r"[-_]", re.sub(r"\.\w+$", "", ultimo[0]))) > 3


RE_BACHECA_RETE = re.compile(r"(?i)(r[ée]seau|network|membres?|members?|adh[ée]rents?|bourse|soci[i]?\b|"
                             r"partner-jobs|jobs-in-the-sector|job-board)")


def bacheca_di_rete(url):
    """Bacheche con gli annunci delle aziende socie di un cluster/associazione
    ("offres d'emploi du réseau", "bourse à l'emploi"): non sono annunci
    dell'azienda in lista."""
    return bool(RE_BACHECA_RETE.search(urlparse(url).path))

PERCORSI_COMUNI = ["careers", "jobs", "lavora-con-noi", "carrieres", "recrutement", "nous-rejoindre",
                   "join-us", "work-with-us", "en/careers", "it/lavora-con-noi", "fr/recrutement",
                   "fr/carrieres", "en/jobs", "about/careers", "company/careers"]


def _html(url):
    r = tf._get(url, rapida=True, timeout=12, headers={"Accept": "text/html"})
    return r.text, getattr(r, "url", url) or url


def link_carriere(html, base):
    """(fonti da portali linkati, miglior link alla pagina carriere o '')."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    host = urlparse(base).netloc.replace("www.", "")
    portali, candidati = {}, []
    for a in soup.find_all(["a", "iframe"], href=True) + soup.find_all("iframe", src=True):
        href = urljoin(base, a.get("href") or a.get("src")).split("#")[0]
        f = fonte_da_url(href)
        if f:
            portali.setdefault(tf.chiave_fonte(f), f)
            continue
        if urlparse(href).netloc.replace("www.", "") != host:
            continue
        testo = a.get_text(" ", strip=True)[:60]
        if sembra_articolo(href) or bacheca_di_rete(href):
            continue
        if RE_CARRIERE.search(urlparse(href).path) or (testo and RE_CARRIERE.search(testo)):
            # Preferisci i link più "parlanti" e con percorso corto
            punti = (2 if RE_CARRIERE.search(urlparse(href).path) else 0) + (1 if RE_CARRIERE.search(testo) else 0)
            candidati.append((-punti, len(href), href))
    migliore = sorted(candidati)[0][2] if candidati else ""
    return list(portali.values()), migliore


def trova_fonti_sito(sito):
    """Fonti trovate a partire dal sito ufficiale. Lista vuota se nulla.
    Un portale linkato dal sito è verificato per costruzione; una pagina
    carriere si tiene solo se parla davvero di lavoro (sembra_pagina_lavoro)."""
    try:
        html, finale = _html(sito)
    except tf.FonteErrore:
        return []
    portali, carriere = link_carriere(html, finale)
    nota = f"linkato da {urlparse(finale).netloc}"
    candidate = [carriere] if carriere else [urljoin(finale, p) for p in PERCORSI_COMUNI]
    for url in candidate:
        if portali:
            break
        try:
            h, fin = _html(url)
        except tf.FonteErrore:
            continue
        # Conta l'indirizzo FINALE: se la pagina carriere rimanda alla home non vale
        # (e WordPress rimanda "/recrutement" all'articolo dal nome più simile)
        if (not RE_CARRIERE.search(urlparse(fin).netloc + urlparse(fin).path)
                or bacheca_di_rete(fin) or sembra_articolo(fin)):
            continue
        # La pagina carriere spesso rimanda a sua volta al portale
        portali, _ = link_carriere(h, fin)
        if portali:
            nota = f"linkato dalla pagina carriere {fin}"
            break
        if sembra_pagina_lavoro(h):
            return [{"tipo": "pagina", "url": fin, "verifica": f"pagina carriere del sito {urlparse(finale).netloc}"}]
        if carriere:
            break                       # la pagina linkata non parla di lavoro: niente percorsi a caso
    # Solo portali con slug plausibile (es. "jobs.smartrecruiters.com/ni/…" non è uno slug)
    portali = [f for f in portali if len(str(f.get("slug") or f.get("url") or "")) >= 3]
    return [{**f, "verifica": nota} for f in portali][:3]


def main():
    aziende = json.load(open("dati/aziende.json", encoding="utf-8"))["aziende"]
    ids = {a["id"] for a in aziende}
    print("Scarico CORDIS (~37 MB)…", flush=True)
    siti = siti_da_cordis(scarica_organization_csv(), ids)
    if len(siti) < 100:
        sys.exit(f"Solo {len(siti)} siti trovati: dati CORDIS inattesi, file non scritto")
    with open(SITI_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(siti.items())), f, ensure_ascii=False, indent=0)
        f.write("\n")
    print(f"{len(siti)} aziende su {len(ids)} con sito ufficiale → {SITI_FILE}")


if __name__ == "__main__":
    main()
