"""
Fonti degli annunci per le aziende della lista "Aziende Target Europa".

Centinaia di aziende diverse non si possono seguire con uno scraper ciascuna:
qui si leggono i portali di selezione con API pubblica (Lever, Greenhouse,
Workable, SmartRecruiters, Ashby, Recruitee, Personio, Workday), le pagine
aziendali di Welcome to the Jungle e, come ultima risorsa, una pagina
"carriere" qualunque (si segnalano i link nuovi).

Ogni lettore restituisce una lista di offerte nel formato comune:
    {"titolo", "location", "paese" (codice ISO o ""), "remoto" (bool),
     "url", "data" (AAAA-MM-GG o "")}
e solleva FonteErrore se la fonte non risponde (≠ "0 offerte").
"""
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8,it;q=0.7",
}
# Tetto per fonte: i grandi gruppi (Workday, SmartRecruiters) hanno migliaia
# di annunci nel mondo; oltre questo numero ci si ferma.
MAX_OFFERTE_FONTE = 3000


class FonteErrore(Exception):
    """La fonte non ha risposto o ha risposto in modo inatteso."""


class NonTrovata(FonteErrore):
    """La fonte non esiste (404): usata dalla scoperta automatica."""


def _sessione():
    retry = Retry(total=2, connect=2, read=2, status=2, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None,
                  respect_retry_after_header=True, raise_on_status=False)
    s = requests.Session()
    ad = HTTPAdapter(max_retries=retry, pool_maxsize=32)
    s.mount("https://", ad)
    s.mount("http://", ad)
    return s


SESSION = _sessione()


def _get(url, metodo="GET", **kw):
    try:
        r = SESSION.request(metodo, url, headers={**HEADERS, **kw.pop("headers", {})},
                            timeout=kw.pop("timeout", 20), **kw)
    except requests.RequestException as e:
        raise FonteErrore(f"{url}: {e.__class__.__name__}") from e
    if r.status_code in (404, 410):
        raise NonTrovata(f"{url}: {r.status_code}")
    if r.status_code >= 400:
        raise FonteErrore(f"{url}: HTTP {r.status_code}")
    return r


def _json(url, **kw):
    r = _get(url, **kw)
    try:
        return r.json()
    except ValueError as e:
        raise FonteErrore(f"{url}: risposta non JSON") from e


def _iso(valore):
    """Data ISO (anche con ora) o millisecondi epoch → AAAA-MM-GG."""
    if valore in (None, ""):
        return ""
    if isinstance(valore, (int, float)):
        return datetime.fromtimestamp(valore / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(valore))
    return m.group(1) if m else ""


def _offerta(titolo, url, location="", paese="", remoto=False, data=""):
    return {"titolo": re.sub(r"\s+", " ", str(titolo or "")).strip(),
            "location": re.sub(r"\s+", " ", str(location or "")).strip(),
            "paese": (paese or "").upper()[:2], "remoto": bool(remoto),
            "url": url or "", "data": data or ""}


# ============================================================
#  Lettori per portale
# ============================================================

def lever(slug, eu=False, **_):
    base = "api.eu.lever.co" if eu else "api.lever.co"
    dati = _json(f"https://{base}/v0/postings/{slug}?mode=json")
    if not isinstance(dati, list):
        raise FonteErrore(f"lever {slug}: formato inatteso")
    out = []
    for j in dati:
        cat = j.get("categories") or {}
        luoghi = cat.get("allLocations") or [cat.get("location")]
        out.append(_offerta(j.get("text"), j.get("hostedUrl"),
                            " / ".join(x for x in luoghi if x), j.get("country"),
                            j.get("workplaceType") == "remote", _iso(j.get("createdAt"))))
    return out


def greenhouse(slug, **_):
    dati = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return [_offerta(j.get("title"), j.get("absolute_url"), (j.get("location") or {}).get("name"),
                     data=_iso(j.get("first_published") or j.get("updated_at")))
            for j in dati.get("jobs", [])]


def workable(slug, **_):
    dati = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    out = []
    for j in dati.get("jobs", []):
        luoghi = j.get("locations") or [j]
        loc = " / ".join(", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in luoghi)
        paese = (luoghi[0].get("countryCode") or "") if luoghi else ""
        url = j.get("url") or (f"https://apply.workable.com/j/{j['shortcode']}" if j.get("shortcode") else "")
        out.append(_offerta(j.get("title"), url, loc, paese, j.get("telecommuting"),
                            _iso(j.get("published_on") or j.get("created_at"))))
    return out


def smartrecruiters(slug, **_):
    out, offset = [], 0
    while offset < MAX_OFFERTE_FONTE:
        dati = _json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                     params={"limit": 100, "offset": offset})
        pagina = dati.get("content") or []
        for j in pagina:
            l = j.get("location") or {}
            loc = l.get("fullLocation") or ", ".join(x for x in (l.get("city"), l.get("country")) if x)
            out.append(_offerta(j.get("name"), f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                                loc, l.get("country"), l.get("remote"), _iso(j.get("releasedDate"))))
        offset += 100
        if not pagina or offset >= (dati.get("totalFound") or 0):
            break
    return out


def ashby(slug, **_):
    dati = _json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in dati.get("jobs", []):
        luoghi = [j.get("location")] + [x.get("location") for x in j.get("secondaryLocations") or []]
        paese = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        out.append(_offerta(j.get("title"), j.get("jobUrl"), " / ".join(x for x in luoghi if x),
                            paese if len(paese) == 2 else "", j.get("isRemote"),
                            _iso(j.get("publishedAt"))))
    return out


def recruitee(slug, **_):
    dati = _json(f"https://{slug}.recruitee.com/api/offers/")
    out = []
    for j in dati.get("offers", []):
        if j.get("status") not in (None, "published"):
            continue
        out.append(_offerta(j.get("title"), j.get("careers_url"),
                            j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x),
                            j.get("country_code"), j.get("remote"), _iso(j.get("published_at"))))
    return out


def personio(slug, dominio="jobs.personio.de", **_):
    r = _get(f"https://{slug}.{dominio}/xml")
    try:
        radice = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise FonteErrore(f"personio {slug}: XML non valido") from e
    out = []
    for p in radice.iter("position"):
        testo = lambda tag: (p.findtext(tag) or "").strip()
        sedi = [testo("office")] + [(o.text or "").strip() for o in p.iter("office")
                                    if o is not p.find("office")]
        sedi = list(dict.fromkeys(s for s in sedi if s))
        out.append(_offerta(testo("name"), f"https://{slug}.{dominio}/job/{testo('id')}",
                            " / ".join(sedi), data=_iso(testo("createdAt"))))
    return out


def _workday_data(testo):
    t = (testo or "").lower()
    oggi = datetime.now()
    if "today" in t or "aujourd" in t or "oggi" in t:
        return oggi.strftime("%Y-%m-%d")
    if "yesterday" in t or "hier" in t or "ieri" in t:
        return (oggi - timedelta(days=1)).strftime("%Y-%m-%d")
    m = re.search(r"(\d+)\s*\+", t)
    if m:
        return ""          # "30+ days ago": data reale ignota (e comunque vecchia)
    m = re.search(r"(\d+)", t)
    return (oggi - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d") if m else ""


# Facet di Workday da selezionare (paesi/città del focus): riduce migliaia di
# annunci nel mondo a quelli in Francia e Italia. Il filtro fine è comunque locale.
WORKDAY_FACET_RE = re.compile(r"\b(france|italy|italia|paris|ile[- ]de[- ]france|île[- ]de[- ]france)\b", re.I)


def _workday_facet(facets):
    """{facetParameter: [id, ...]} dei valori che corrispondono al focus."""
    scelti = {}

    def visita(param, valori):
        for v in valori or []:
            if v.get("values"):                       # gruppo annidato
                visita(v.get("facetParameter") or param, v["values"])
            elif v.get("id") and WORKDAY_FACET_RE.search(v.get("descriptor") or ""):
                scelti.setdefault(param, []).append(v["id"])

    for f in facets or []:
        if re.search(r"(?i)location|country|pays", f.get("facetParameter", "")):
            visita(f.get("facetParameter"), f.get("values"))
    return scelti


def workday(url, **_):
    """url = pagina pubblica, es. https://thales.wd3.myworkdayjobs.com/fr-FR/Careers"""
    u = urlparse(url)
    parti = [p for p in u.path.split("/") if p]
    if not parti:
        raise FonteErrore(f"workday: URL senza sito ({url})")
    lingua = parti[0] if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parti[0]) else ""
    sito = parti[-1] if not lingua or len(parti) > 1 else ""
    tenant = u.netloc.split(".")[0]
    api = f"https://{u.netloc}/wday/cxs/{tenant}/{sito}/jobs"
    base = f"https://{u.netloc}/{lingua + '/' if lingua else ''}{sito}"

    def pagina(offset, facet):
        return _json(api, metodo="POST", json={"appliedFacets": facet, "limit": 20,
                                                 "offset": offset, "searchText": ""},
                     headers={"Content-Type": "application/json"})

    primo = pagina(0, {})
    facet = _workday_facet(primo.get("facets"))
    if facet:
        primo = pagina(0, facet)
    totale = primo.get("total") or 0
    out, offset, dati = [], 0, primo
    while True:
        righe = dati.get("jobPostings") or []
        for j in righe:
            out.append(_offerta(j.get("title"), base + (j.get("externalPath") or ""),
                                j.get("locationsText"), data=_workday_data(j.get("postedOn"))))
        offset += 20
        if not righe or offset >= min(totale, MAX_OFFERTE_FONTE):
            break
        dati = pagina(offset, facet)
    return out


# --- Welcome to the Jungle --------------------------------------------------

def _wttj_da_link(slug, href, testo):
    """/fr/companies/hello-tomorrow/jobs/deep-tech-intern_paris_HT_Vdxzq2W →
    titolo dal testo del link (o dallo slug), città dalla parte dopo "_"."""
    coda = href.split(f"/companies/{slug}/jobs/", 1)[1].split("?")[0].strip("/")
    pezzi = coda.split("_")
    citta = pezzi[1].replace("-", " ").title() if len(pezzi) > 1 else ""
    titolo = (testo or "").strip() or pezzi[0].replace("-", " ").capitalize()
    url = "https://www.welcometothejungle.com/fr/companies/" + slug + "/jobs/" + coda
    return _offerta(titolo, url, citta)


def wttj(slug, **_):
    """Pagina pubblica dell'azienda su Welcome to the Jungle. Se il codice HTML
    non contiene gli annunci (pagina costruita in JavaScript) si usa Playwright."""
    url = f"https://www.welcometothejungle.com/fr/companies/{slug}/jobs"
    html = _get(url, headers={"Accept": "text/html"}).text
    out = _wttj_estrai(slug, html)
    if not out:
        html_js = _html_con_browser(url)
        if html_js:
            out = _wttj_estrai(slug, html_js)
    return out


def _wttj_estrai(slug, html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    visti, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if f"/companies/{slug}/jobs/" not in href:
            continue
        o = _wttj_da_link(slug, href, a.get_text(" ", strip=True)[:160])
        if o["url"] in visti or "spontaneous" in o["url"] or "candidature-spontanee" in o["url"]:
            continue
        visti.add(o["url"])
        out.append(o)
    return out


# --- Pagina carriere generica -----------------------------------------------

RE_LINK_ANNUNCIO = re.compile(
    r"(job|jobs|career|careers|carriere|carrière|vacanc|position|posizion|offre|offres|emploi|"
    r"recrut|stage|intern|lavora|opportunit|opening|stelle|annonce|apply|candidat)", re.I)
RE_LINK_MENU = re.compile(
    r"^(careers?|jobs?|carri[eè]res?|lavora con noi|work with us|join us|nous rejoindre|"
    r"rejoignez[- ]nous|apply|candidature spontan\w*|spontaneous application|open application|"
    r"posizioni aperte|offres d'emploi|our offers|see all|vedi tutt\w*|voir tout\w*)$", re.I)
ATS_DOMINI = ("lever.co", "greenhouse.io", "workable.com", "smartrecruiters.com", "ashbyhq.com",
              "recruitee.com", "personio.", "teamtailor.com", "welcometothejungle.com",
              "myworkdayjobs.com", "join.com", "bamboohr.com", "jobs.")


def pagina(url, filtro=None, js=False, **_):
    """Link che sembrano annunci in una pagina "carriere". Senza date né sedi:
    la newsletter segnala i link comparsi dall'ultima volta."""
    html = _html_con_browser(url) if js else _get(url, headers={"Accept": "text/html"}).text
    if html is None:
        raise FonteErrore(f"pagina {url}: browser non disponibile")
    return estrai_link_annunci(html, url, filtro)


def estrai_link_annunci(html, url, filtro=None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["nav", "header", "footer", "script", "style"]):
        t.decompose()
    host = urlparse(url).netloc.replace("www.", "")
    rf = re.compile(filtro, re.I) if filtro else None
    visti, out = set(), []
    for a in soup.find_all("a", href=True):
        testo = a.get_text(" ", strip=True)
        href = urljoin(url, a["href"]).split("#")[0]
        if not (8 <= len(testo) <= 160) or RE_LINK_MENU.match(testo) or href.rstrip("/") == url.rstrip("/"):
            continue
        dominio = urlparse(href).netloc.replace("www.", "")
        su_ats = any(d in dominio for d in ATS_DOMINI)
        if dominio != host and not su_ats:
            continue
        if rf:
            if not rf.search(href + " " + testo):
                continue
        elif not su_ats and not RE_LINK_ANNUNCIO.search(urlparse(href).path):
            continue
        if href in visti or href.startswith("mailto:"):
            continue
        visti.add(href)
        out.append(_offerta(testo, href))
    return out


def _html_con_browser(url):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(user_agent=HEADERS["User-Agent"])
            pg.goto(url, timeout=45000, wait_until="domcontentloaded")
            pg.wait_for_timeout(5000)
            html = pg.content()
            b.close()
            return html
    except Exception as e:
        raise FonteErrore(f"browser {url}: {e.__class__.__name__}") from e


LETTORI = {"lever": lever, "greenhouse": greenhouse, "workable": workable,
           "smartrecruiters": smartrecruiters, "ashby": ashby, "recruitee": recruitee,
           "personio": personio, "workday": workday, "wttj": wttj, "pagina": pagina}


def leggi_fonte(fonte: dict) -> list:
    tipo = fonte.get("tipo")
    if tipo not in LETTORI:
        raise FonteErrore(f"tipo di fonte sconosciuto: {tipo}")
    parametri = {k: v for k, v in fonte.items() if k not in ("tipo", "nota", "verifica", "trovata")}
    return LETTORI[tipo](**parametri)


def chiave_fonte(fonte: dict) -> str:
    return fonte["tipo"] + ":" + str(fonte.get("slug") or fonte.get("url"))


# ============================================================
#  Dove si trova l'offerta
# ============================================================

RE_PARIGI = re.compile(
    r"\b(paris|[iî]le[- ]de[- ]france|idf|la d[ée]fense|boulogne[- ]billancourt|issy[- ]les|"
    r"neuilly|levallois|courbevoie|puteaux|nanterre|saint[- ]denis|saint[- ]ouen|montrouge|"
    r"malakoff|clichy|saclay|palaiseau|massy|v[ée]lizy|versailles|guyancourt|rueil|ivry|"
    r"vincennes|montreuil|cergy|[ée]lancourt|gennevilliers|meudon|saint[- ]cloud|suresnes|"
    r"ch[âa]tillon|bagneux|arcueil|gentilly|marne[- ]la[- ]vall[ée]e|noisy|roissy|orly|rungis|"
    r"[ée]vry|trappes|plaisir|les ulis|orsay|gif[- ]sur[- ]yvette|colombes|bezons|"
    r"saint[- ]quentin[- ]en[- ]yvelines|hauts[- ]de[- ]seine|yvelines|essonne|val[- ]de[- ]marne|"
    r"seine[- ]saint[- ]denis|val[- ]d'oise)\b", re.I)
RE_ITALIA = re.compile(
    r"\b(ital(y|ia|ie|ien)|milan[oe]?|rom[ae]|turin|torino|genova|genoa|bologna|firenze|florence|"
    r"napoli|naples|padova|padua|venezia|venice|mestre|verona|bari|pisa|trento|trieste|bergamo|"
    r"brescia|modena|parma|cagliari|palermo|catania|lecce|ancona|perugia|pescara|udine|como|"
    r"monza|livorno|la spezia|fano|vicenza|treviso|ferrara|bolzano|aosta|ivrea|pavia|siena|"
    r"lucca|novara|ravenna|rimini|salerno|caserta|taranto|messina|sassari|arezzo|pomezia|"
    r"frascati|ispra|cosenza|potenza|campobasso|l'aquila|sesto san giovanni|assago|segrate)\b", re.I)
RE_REMOTO = re.compile(r"\b(remote|remoto|full[- ]?remote|t[ée]l[ée]travail|anywhere|home[- ]based|"
                       r"smart ?working|work from home)\b", re.I)
RE_FRANCIA = re.compile(r"\b(france|francia)\b", re.I)

# Sezioni della newsletter, in ordine di priorità
SEZIONI = [("PAR", "Parigi e Île-de-France"), ("IT", "Italia"), ("REMOTO", "Da remoto"),
           ("ND", "Sede non indicata"), ("ALTRO", "Altre sedi")]


def luogo(o: dict) -> str:
    """PAR / IT / REMOTO / ALTRO / ND. Parigi vince su tutto: un annuncio
    "Paris / Milano" finisce sotto Parigi."""
    loc, paese = o.get("location") or "", (o.get("paese") or "").upper()
    if RE_PARIGI.search(loc):
        return "PAR"
    if paese == "IT" or RE_ITALIA.search(loc):
        return "IT"
    if o.get("remoto") or RE_REMOTO.search(loc) or RE_REMOTO.search(o.get("titolo") or ""):
        return "REMOTO"
    if not loc and not paese:
        return "ND"
    return "ALTRO"


# ============================================================
#  Scoperta automatica (solo aziende della lista)
# ============================================================

SUFFISSI = {
    "srl", "spa", "sas", "sa", "sl", "sarl", "gmbh", "ggmbh", "mbh", "bv", "nv", "ab", "as", "ag",
    "kg", "co", "ug", "oy", "oe", "pc", "ike", "ltd", "limited", "lda", "unipessoal", "asbl",
    "eesv", "sro", "uab", "sia", "aps", "ewiv", "dac", "plc", "llc", "inc", "sp", "zoo", "and",
    "societa", "benefit", "cooperativa", "sociedad", "limitada", "e", "c", "di", "the", "s",
    "r", "l", "a", "p", "i", "k",
}
# Parole troppo comuni per identificare un'azienda da sole
GENERICHE = {
    "consulting", "consultants", "consultancy", "consult", "innovation", "innovations", "services",
    "service", "international", "group", "groupe", "gruppo", "europe", "european", "europa",
    "technology", "technologies", "tech", "solutions", "solution", "network", "foundation",
    "fondazione", "fundacion", "institute", "istituto", "research", "development", "energy",
    "energia", "digital", "global", "partners", "associazione", "association", "centre", "center",
    "centro", "advisory", "management", "sustainable", "systems", "engineering", "italia",
    "france", "france", "de", "la", "le", "les", "des", "del", "della", "per", "et", "for", "of",
    "in", "und", "y", "da", "do", "eu", "it", "new", "smart", "green", "data", "labs", "lab",
}


def _ascii(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def parole(nome: str) -> list:
    """Parole significative del nome, senza forme societarie."""
    t = re.sub(r"\(.*?\)", " ", _ascii(nome))
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return [w for w in t.split() if w not in SUFFISSI]


def slug_candidati(nome: str) -> list:
    p = parole(nome)
    if not p:
        return []
    c = ["".join(p), "-".join(p)]
    if len(p) > 2:
        c += ["".join(p[:2]), "-".join(p[:2])]
    if p[0] not in GENERICHE and len(p[0]) >= 4:
        c.append(p[0])
    return [s for s in dict.fromkeys(c) if len(s) >= 3][:5]


def nome_corrisponde(nostro: str, loro: str) -> bool:
    """Il nome restituito dal portale è quello dell'azienda della lista?
    Le parole distintive del nostro nome devono comparire nel loro, e la
    prima parola distintiva del loro nel nostro (evita "Innova" ↔ "Innovaphone")."""
    a = [w for w in parole(nostro) if w not in GENERICHE] or parole(nostro)
    b_tutte = parole(loro)
    b = [w for w in b_tutte if w not in GENERICHE] or b_tutte
    if not a or not b:
        return False
    if a[0] not in b_tutte and "".join(a) not in "".join(b_tutte):
        return False
    return b[0] in parole(nostro) or b[0] == "".join(a)


def testo_cita_nome(nostro: str, testi: list) -> bool:
    """Per i portali che non danno il nome dell'azienda (Lever, Ashby): il nome
    deve comparire nel testo degli annunci."""
    a = [w for w in parole(nostro) if w not in GENERICHE] or parole(nostro)
    if not a:
        return False
    frase = r"\b" + r"[\s\-]*".join(map(re.escape, a[:3])) + r"\b"
    return any(re.search(frase, _ascii(t)) for t in testi if t)


def _prova(tipo, slug, nome):
    """(fonte, n. offerte) se lo slug esiste ED è dell'azienda, altrimenti None."""
    try:
        if tipo == "greenhouse":
            b = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
            if nome_corrisponde(nome, b.get("name", "")):
                return {"tipo": tipo, "slug": slug, "verifica": f"nome: {b.get('name')}"}
        elif tipo == "workable":
            b = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
            if nome_corrisponde(nome, b.get("name", "")):
                return {"tipo": tipo, "slug": slug, "verifica": f"nome: {b.get('name')}"}
        elif tipo == "smartrecruiters":
            b = _json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 1})
            loro = ((b.get("content") or [{}])[0].get("company") or {}).get("name", "")
            if loro and nome_corrisponde(nome, loro):
                return {"tipo": tipo, "slug": slug, "verifica": f"nome: {loro}"}
        elif tipo == "recruitee":
            b = _json(f"https://{slug}.recruitee.com/api/offers/")
            loro = ((b.get("offers") or [{}])[0]).get("company_name", "")
            if loro and nome_corrisponde(nome, loro):
                return {"tipo": tipo, "slug": slug, "verifica": f"nome: {loro}"}
        elif tipo in ("lever", "lever-eu"):
            eu = tipo == "lever-eu"
            b = _json(f"https://{'api.eu' if eu else 'api'}.lever.co/v0/postings/{slug}?mode=json")
            testi = [j.get("descriptionPlain", "") + " " + j.get("additionalPlain", "") for j in b[:20]]
            if b and testo_cita_nome(nome, testi):
                f = {"tipo": "lever", "slug": slug, "verifica": "nome citato negli annunci"}
                if eu:
                    f["eu"] = True
                return f
        elif tipo == "ashby":
            b = _json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            testi = [j.get("descriptionPlain", "") for j in (b.get("jobs") or [])[:20]]
            if testo_cita_nome(nome, testi):
                return {"tipo": tipo, "slug": slug, "verifica": "nome citato negli annunci"}
        elif tipo == "wttj":
            html = _get(f"https://www.welcometothejungle.com/fr/companies/{slug}",
                        headers={"Accept": "text/html"}).text
            m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            loro = re.split(r"\s[\|:–-]\s", (m.group(1) if m else "").strip())[0]
            if loro and nome_corrisponde(nome, loro):
                return {"tipo": tipo, "slug": slug, "verifica": f"nome: {loro}"}
    except (FonteErrore, ValueError, AttributeError, TypeError, IndexError):
        return None
    return None


TIPI_SCOPERTA = ["greenhouse", "lever", "lever-eu", "workable", "smartrecruiters", "ashby", "recruitee"]


def scopri(azienda: dict) -> list:
    """Fonti verificate per un'azienda della lista. WTTJ solo per le aziende
    con sede in Francia (lì è il portale più usato)."""
    tipi = TIPI_SCOPERTA + (["wttj"] if "FR" in (azienda.get("p") or "").split(",") else [])
    trovate, usati = [], set()
    for tipo in tipi:
        for slug in slug_candidati(azienda["n"]):
            f = _prova(tipo, slug, azienda["n"])
            if f and f["tipo"] not in usati:
                trovate.append(f)
                usati.add(f["tipo"])
                break
    return trovate
