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
import html as html_lib
import re
import threading
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
# Lingua nei percorsi Workday: "fr-FR", "en-US", ma anche solo "es" (Repsol)
RE_LINGUA = re.compile(r"[a-z]{2}(?:-[A-Za-z]{2})?")
WORKDAY_MAX = 2000          # limite di Workday per una singola ricerca


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
# Per la scoperta: nessun nuovo tentativo e niente attese su Retry-After.
# Uno slug che non risponde al primo colpo si riprova la settimana dopo.
SESSION_RAPIDA = requests.Session()
SESSION_RAPIDA.mount("https://", HTTPAdapter(max_retries=0, pool_maxsize=32))


def _get(url, metodo="GET", **kw):
    sessione = SESSION_RAPIDA if kw.pop("rapida", False) else SESSION
    try:
        r = sessione.request(metodo, url, headers={**HEADERS, **kw.pop("headers", {})},
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


def _offerta(titolo, url, location="", paese="", remoto=False, data="", testo=None, dettaglio=""):
    """testo = descrizione dell'annuncio (per il filtro lingua), se il portale la dà
    già nell'elenco; dettaglio = indirizzo API da cui leggerla (Workday, SmartRecruiters)."""
    o = {"titolo": re.sub(r"\s+", " ", str(titolo or "")).strip(),
         "location": re.sub(r"\s+", " ", str(location or "")).strip(),
         "paese": (paese or "").upper()[:2], "remoto": bool(remoto),
         "url": url or "", "data": data or ""}
    if testo is not None:
        o["testo"] = _testo(testo)
    if dettaglio:
        o["dettaglio"] = dettaglio
    return o


MAX_TESTO = 8000


def _testo(html_o_testo):
    """Testo semplice (a capo tra i blocchi) da HTML o testo, tagliato a MAX_TESTO."""
    t = html_lib.unescape(str(html_o_testo or ""))
    if "<" in t:
        t = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h\d|li)[^>]*>", "\n", t)
        t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*", "\n", t).strip()[:MAX_TESTO]


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
        testo = "\n".join([j.get("descriptionPlain") or ""]
                          + [f"{x.get('text', '')}\n{x.get('content', '')}" for x in j.get("lists") or []]
                          + [j.get("additionalPlain") or ""])
        out.append(_offerta(j.get("text"), j.get("hostedUrl"),
                            " / ".join(x for x in luoghi if x), j.get("country"),
                            j.get("workplaceType") == "remote", _iso(j.get("createdAt")), testo))
    return out


def greenhouse(slug, **_):
    dati = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    return [_offerta(j.get("title"), j.get("absolute_url"), (j.get("location") or {}).get("name"),
                     data=_iso(j.get("first_published") or j.get("updated_at")), testo=j.get("content"))
            for j in dati.get("jobs", [])]


def workable(slug, **_):
    dati = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"})
    out = []
    for j in dati.get("jobs", []):
        luoghi = j.get("locations") or [j]
        loc = " / ".join(", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in luoghi)
        paese = (luoghi[0].get("countryCode") or "") if luoghi else ""
        url = j.get("url") or (f"https://apply.workable.com/j/{j['shortcode']}" if j.get("shortcode") else "")
        testo = " ".join(j.get(k) or "" for k in ("description", "requirements", "benefits")) or None
        out.append(_offerta(j.get("title"), url, loc, paese, j.get("telecommuting"),
                            _iso(j.get("published_on") or j.get("created_at")), testo))
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
                                loc, l.get("country"), l.get("remote"), _iso(j.get("releasedDate")),
                                dettaglio=f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j.get('id')}"))
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
                            _iso(j.get("publishedAt")), j.get("descriptionPlain") or j.get("descriptionHtml")))
    return out


def recruitee(slug, **_):
    dati = _json(f"https://{slug}.recruitee.com/api/offers/")
    out = []
    for j in dati.get("offers", []):
        if j.get("status") not in (None, "published"):
            continue
        out.append(_offerta(j.get("title"), j.get("careers_url"),
                            j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x),
                            j.get("country_code"), j.get("remote"), _iso(j.get("published_at")),
                            f"{j.get('description') or ''}\n{j.get('requirements') or ''}"))
    return out


def personio(slug, dominio="jobs.personio.de", **_):
    try:
        r = _get(f"https://{slug}.{dominio}/xml")
    except NonTrovata:
        # Feed XML disattivato dall'azienda (Naturland): si legge la pagina pubblica
        html = _get(f"https://{slug}.{dominio}/", headers={"Accept": "text/html"}).text
        return _personio_html(slug, dominio, html)
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
        descr = "\n".join(f"{d.findtext('name') or ''}\n{d.findtext('value') or ''}"
                          for d in p.iter("jobDescription"))
        out.append(_offerta(testo("name"), f"https://{slug}.{dominio}/job/{testo('id')}",
                            " / ".join(sedi), data=_iso(testo("createdAt")), testo=descr))
    return out


def _personio_html(slug, dominio, html):
    from bs4 import BeautifulSoup
    out, visti = [], set()
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        m = re.search(r"/job/(\d+)", a["href"])
        if not m or m.group(1) in visti:
            continue
        visti.add(m.group(1))
        righe = [t for t in a.stripped_strings]
        out.append(_offerta(righe[0] if righe else "", f"https://{slug}.{dominio}/job/{m.group(1)}",
                            " ".join(righe[1:])[:80]))
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


# Facet di Workday: si selezionano i PAESI del focus (Francia, Italia), non le
# singole sedi: un filtro per sede ("Paris 9ème") perderebbe il resto dell'Île-de-France.
# Il filtro fine (Parigi/IDF, Italia, remoto) è comunque locale.
WORKDAY_PAESI_RE = re.compile(r"^\s*(france|italy|italia|italie|frankreich|italien)\s*$", re.I)


def _workday_facet(facets):
    """{facetParameter: [id, ...]} con i valori "Francia"/"Italia" del primo
    facet di tipo paese trovato. Vuoto se il sito non ha un facet per paese
    (si leggono allora tutti gli annunci, fino a MAX_OFFERTE_FONTE)."""
    trovati = {}

    def visita(param, valori):
        for v in valori or []:
            if v.get("values"):                       # gruppo annidato
                visita(v.get("facetParameter") or param, v["values"])
            elif v.get("id") and WORKDAY_PAESI_RE.match(v.get("descriptor") or ""):
                trovati.setdefault(param, []).append(v["id"])

    for f in facets or []:
        if re.search(r"(?i)location|country|pays", f.get("facetParameter", "")):
            visita(f.get("facetParameter"), f.get("values"))
    if not trovati:
        return {}
    # Preferisci il parametro che parla di paese; altrimenti quello con più valori
    param = next((p for p in trovati if re.search(r"(?i)country|pays", p)),
                 max(trovati, key=lambda p: len(trovati[p])))
    return {param: trovati[param]}


def workday(url, **_):
    """url = pagina pubblica, es. https://thales.wd3.myworkdayjobs.com/fr-FR/Careers"""
    u = urlparse(url)
    parti = [p for p in u.path.split("/") if p]
    if not parti:
        raise FonteErrore(f"workday: URL senza sito ({url})")
    lingua = parti[0] if RE_LINGUA.fullmatch(parti[0]) else ""
    sito = (parti[1] if lingua else parti[0]) if len(parti) > (1 if lingua else 0) else ""
    if not sito:
        raise FonteErrore(f"workday: URL senza nome del sito ({url})")
    tenant = u.netloc.split(".")[0]
    api = f"https://{u.netloc}/wday/cxs/{tenant}/{sito}/jobs"
    base = f"https://{u.netloc}/{lingua + '/' if lingua else ''}{sito}"

    def pagina(offset, facet):
        return _json(api, metodo="POST", json={"appliedFacets": facet, "limit": 20,
                                                 "offset": offset, "searchText": ""},
                     headers={"Content-Type": "application/json"})

    primo = pagina(0, {})
    facet = _workday_facet(primo.get("facets"))
    # Un paese alla volta: Workday restituisce al massimo 2000 risultati per
    # ricerca e la Francia da sola può superarli (Thales).
    ricerche = [{k: [v]} for k, valori in facet.items() for v in valori] or [{}]
    out, visti = [], set()
    for filtro in ricerche:
        dati = pagina(0, filtro) if filtro else primo
        totale, offset = dati.get("total") or 0, 0
        while True:
            righe = dati.get("jobPostings") or []
            for j in righe:
                url_j = base + (j.get("externalPath") or "")
                if url_j in visti:
                    continue
                visti.add(url_j)
                out.append(_offerta(j.get("title"), url_j, j.get("locationsText"),
                                    data=_workday_data(j.get("postedOn")),
                                    dettaglio=f"https://{u.netloc}/wday/cxs/{tenant}/{sito}{j.get('externalPath') or ''}"
                                    if j.get("externalPath") else ""))
            offset += 20
            if not righe or offset >= min(totale, WORKDAY_MAX):
                break
            dati = pagina(offset, filtro)
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
    try:
        html = _get(url, headers={"Accept": "text/html"}).text
    except NonTrovata:
        raise
    except FonteErrore:
        html = ""                     # es. 403 anti-bot: si prova col browser
    out = _wttj_estrai(slug, html)
    if not out:
        html_js = _html_con_browser(url)
        if html_js:
            out = _wttj_estrai(slug, html_js)
    return out


RE_SPONTANEA = re.compile(r"(?i)(spontan|open[- ]application|talent[- ]pool|candidature[- ]libre)")


def _wttj_estrai(slug, html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    visti, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if f"/companies/{slug}/jobs/" not in href:
            continue
        o = _wttj_da_link(slug, href, a.get_text(" ", strip=True)[:160])
        if o["url"] in visti or RE_SPONTANEA.search(o["url"] + " " + o["titolo"]):
            continue
        visti.add(o["url"])
        out.append(o)
    return out


# --- Pagina carriere generica -----------------------------------------------

# Parole da annuncio nel percorso del link, come parole intere
# ("intern" sì, "international" no).
RE_LINK_ANNUNCIO = re.compile(
    r"(?:^|[/_\-.?=&])(jobs?|careers?|carri[eè]res?|vacanc\w*|positions?|posizion[ei]|offres?|"
    r"emplois?|recrut\w*|stages?|internships?|interns?|lavora\w*|openings?|stellen\w*|annonces?|"
    r"apply|candidat\w*|job-?offers?|offerte|bandi-di-lavoro|selezion[ei])(?=$|[/_\-.?=&])", re.I)
# Nelle pagine carriere generiche un link è un annuncio solo se il testo sembra
# un titolo di lavoro: via "Life at Nokia", "Students and graduates", "Explore all jobs".
RE_TITOLO_LAVORO = re.compile(
    r"(\b(manager|engineer|ing[ée]nieure?|ingegner\w*|ingenieur\w*|ingeniero|consultant\w*|consulente|"
    r"consultor\w*|officer|assistant\w*|assistente|analyst|analyste|analista|developer|d[ée]veloppeu\w*|"
    r"sviluppator\w*|entwickler\w*|technician|technicien\w*|tecnic[oa]|t[ée]cnico|scientist|"
    r"scientifique|researcher|chercheu\w*|ricercat\w*|investigador\w*|coordinator|coordinat\w*|"
    r"specialist|sp[ée]cialiste|specialista|director|directeur|directrice|direttore|head of|team lead\w*|"
    r"lead|charg[ée]e?|responsable|responsabile|chef de projet|stage|stagiaire|intern|internship|"
    r"tirocin\w*|alternan\w*|apprenti\w*|trainee|junior|senior|expert\w*|esperto|advisor|adviser|"
    r"conseill\w*|administrat\w*|accountant|comptable|contabile|controller|architect\w*|designer|"
    r"operator|op[ée]rat(?:eur|rice)|operatore|economist|[ée]conomiste|economista|lawyer|juriste|recruiter|"
    r"secr[ée]tair\w*|segretari\w*|postdoc\w*|ph\.?d|doctora\w*|dottorat\w*|fellow\w*|supervisor|"
    r"auditor|editor|planner|mitarbeiter\w*|referent\w*|sachbearbeiter\w*|berater\w*|leiter\w*|"
    r"praktik\w*|werkstudent\w*|becari[oa]|programmer|data scientist|buyer|acheteu\w*|"
    r"impiegat\w*|addett\w*|project officer|policy officer)\b|"
    r"\b[hf]\s*/\s*[hf]\b|\bm\s*/\s*[fw](?:\s*/\s*[dx])?\b|\(\s*[mfwd](?:\s*/\s*[mfwdx]){1,3}\s*\))", re.I)

# Candidature generiche: non sono offerte (tutte le fonti)
RE_CANDIDATURA_GENERICA = re.compile(
    r"(?i)(^join\b|spontan|open application|candidature (?:libre|ouverte)|talent pool|vivier|"
    r"join (?:our|the) team|join us|work with us|[úu]nete a|lavora con noi|rejoignez[- ]nous|"
    r"candidatura spontanea|initiativbewerbung)")
# Nelle pagine carriere: link a programmi, presentazioni, privacy, ricerche
RE_NON_ANNUNCIO = re.compile(
    r"(?i)(\bprogram(?:me)?s?\b|\bmeet\b|privacy|notice|\bpupils?\b|sch[üu]ler|"
    r"\bstudents?\b|recruitment (?:is )?now open|our business|creating meaningful|"
    r"^operations$|fellowships|^apprenticeships?$|interns and apprentices|"
    r"internship for pupils|find your|discover|d[ée]couvr|why join|life at|our people|"
    r"\bfaq\b|how to apply|alternance et le stage chez)")
# Coda da togliere ai titoli presi da link ("… More Details", "… Lire")
RE_CODA_TITOLO = re.compile(r"(?i)\s*(more details|read more|learn more|lire( la suite)?|en savoir plus|"
                            r"scopri di più|leggi( di più)?|mehr erfahren|details|voir l.offre)\s*$")


def pulisci_titolo(t):
    t = RE_CODA_TITOLO.sub("", re.sub(r"\s+", " ", t or "").strip())
    parole_t = t.split()
    # "R&D Project Manager R&D Project Manager Rome Italy" → una volta sola
    for n in range(len(parole_t) // 2, 0, -1):
        if parole_t[:n] == parole_t[n:2 * n]:
            t = " ".join(parole_t[n:])
            break
    return t


# Parametri che cambiano a ogni visita: tolti dall'URL, altrimenti lo stesso
# annuncio sembrerebbe nuovo ogni giorno.
RE_PARAM_VOLATILI = re.compile(r"(?i)^(utm_\w+|fbclid|gclid|mc_\w+|sessionid|sid|jsessionid|phpsessid|"
                               r"_ga|ref|source|lang|hl)$")


def _url_stabile(href):
    from urllib.parse import parse_qsl, urlencode
    u = urlparse(href)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not RE_PARAM_VOLATILI.match(k)]
    u = u._replace(query=urlencode(q), fragment="")
    return re.sub(r";jsessionid=[^/?]*", "", u.geturl(), flags=re.I)


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
        href = _url_stabile(urljoin(url, a["href"]))
        if not (8 <= len(testo) <= 160) or RE_LINK_MENU.match(testo) or href.rstrip("/") == url.rstrip("/"):
            continue
        dominio = urlparse(href).netloc.replace("www.", "")
        su_ats = any(d in dominio for d in ATS_DOMINI)
        if dominio != host and not su_ats:
            continue
        if rf:
            if not rf.search(href + " " + testo):
                continue
        elif not su_ats and not RE_LINK_ANNUNCIO.search(urlparse(href).path + "?" + urlparse(href).query):
            continue
        testo = pulisci_titolo(testo)
        if (href in visti or href.startswith("mailto:") or "search=" in href
                or not RE_TITOLO_LAVORO.search(testo) or RE_NON_ANNUNCIO.search(testo)):
            continue
        visti.add(href)
        out.append(_offerta(testo, href))
    return out


_BROWSER_LOCK = threading.Lock()


def _html_con_browser(url):
    """HTML dopo l'esecuzione del JavaScript (WTTJ risponde 202 anti-bot alle
    richieste dirette). Un browser alla volta anche con più thread."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with _BROWSER_LOCK, sync_playwright() as p:
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


def descrizione(o: dict) -> str:
    """Descrizione dell'annuncio per il filtro lingua: quella già letta dal
    portale, altrimenti dall'API di dettaglio (Workday, SmartRecruiters) o dalla
    pagina dell'annuncio. "" se non leggibile (l'offerta allora resta)."""
    if o.get("testo") is not None:
        return o["testo"]
    try:
        if "/wday/cxs/" in o.get("dettaglio", ""):
            info = (_json(o["dettaglio"], rapida=True) or {}).get("jobPostingInfo") or {}
            return _testo(info.get("jobDescription"))
        if "api.smartrecruiters.com" in o.get("dettaglio", ""):
            sezioni = ((_json(o["dettaglio"], rapida=True) or {}).get("jobAd") or {}).get("sections") or {}
            return _testo("\n".join((v or {}).get("text", "") for v in sezioni.values()))
        if o.get("url", "").startswith("http") and "welcometothejungle.com" not in o["url"]:
            html = _get(o["url"], rapida=True, headers={"Accept": "text/html"}).text
            html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
            return _testo(html)
    except FonteErrore:
        pass
    return ""


def leggi_fonte(fonte: dict) -> list:
    tipo = fonte.get("tipo")
    if tipo not in LETTORI:
        raise FonteErrore(f"tipo di fonte sconosciuto: {tipo}")
    parametri = {k: v for k, v in fonte.items() if k not in ("tipo", "nota", "verifica", "trovata")}
    return [o for o in LETTORI[tipo](**parametri)
            if o.get("titolo") and not RE_CANDIDATURA_GENERICA.search(o["titolo"])]


def chiave_fonte(fonte: dict) -> str:
    """Identifica il portale. Workday: host + sito, senza la lingua
    (".../fr-FR/Careers" e ".../en-US/Careers" sono lo stesso portale)."""
    if fonte.get("tipo") == "workday":
        u = urlparse(fonte.get("url", ""))
        parti = [p for p in u.path.split("/") if p and not RE_LINGUA.fullmatch(p)]
        return f"workday:{u.netloc.lower()}/{'/'.join(parti[:1])}"
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
    r"seine[- ]saint[- ]denis|val[- ]d'oise|seine[- ]et[- ]marne|le plessis[- ]robinson|clamart|"
    r"antony|sceaux|fontenay[- ]aux[- ]roses|vanves|s[èe]vres|chaville|villejuif|vitry|cachan|"
    r"kremlin[- ]bic[êe]tre|charenton|maisons[- ]alfort|cr[ée]teil|saint[- ]maur|nogent|"
    r"fontenay[- ]sous[- ]bois|rosny|bobigny|pantin|aubervilliers|le bourget|villepinte|tremblay|"
    r"argenteuil|asni[èe]res|bois[- ]colombes|la garenne|saint[- ]germain[- ]en[- ]laye|chatou|"
    r"croissy|le pecq|marly|louveciennes|bougival|jouy[- ]en[- ]josas|buc|saint[- ]cyr[- ]l.[ée]cole|"
    r"montigny[- ]le[- ]bretonneux|coigni[èe]res|maurepas|les mureaux|poissy|mantes|limours|"
    r"br[ée]tigny|linas|montlh[ée]ry|wissous|villebon|courtab(?:oe|œ)uf|corbeil|melun|meaux|"
    r"champs[- ]sur[- ]marne|torcy|lognes|serris|chessy|bussy|pontoise|"
    r"(?:75|77|78|91|92|93|94|95)\d{3})\b", re.I)
RE_ITALIA = re.compile(
    r"\b(ital(y|ia|ie|ien)|milan[oe]?|rom[ae]|turin|torino|genova|genoa|bologna|firenze|florence|"
    r"napoli|naples|padova|padua|venezia|venice|mestre|verona|bari|pisa|trento|trieste|bergamo|"
    r"brescia|modena|parma|cagliari|palermo|catania|lecce|ancona|perugia|pescara|udine|como|"
    r"monza|livorno|la spezia|fano|vicenza|treviso|ferrara|bolzano|aosta|ivrea|pavia|siena|"
    r"lucca|novara|ravenna|rimini|salerno|caserta|taranto|messina|sassari|arezzo|pomezia|"
    r"frascati|ispra|cosenza|potenza|campobasso|l'aquila|sesto san giovanni|assago|segrate)\b", re.I)
RE_REMOTO = re.compile(r"\b(remote|remoto|full[- ]?remote|t[ée]l[ée]travail|anywhere|home[- ]based|"
                       r"smart ?working|work from home)\b", re.I)
# Nel titolo solo forme esplicite: "Remote Sensing Engineer" non è da remoto
RE_REMOTO_TITOLO = re.compile(r"(\bfull[- ]?remote\b|\b100\s?% remote\b|\bremote[- ]first\b|"
                              r"\bfully remote\b|\bt[ée]l[ée]travail (?:complet|total)\b|"
                              r"\(remote\)|[-–] remote\s*$)", re.I)
RE_FRANCIA = re.compile(r"\b(france|francia|frankreich|fr)\b", re.I)

# Sezioni della newsletter, in ordine di priorità
SEZIONI = [("PAR", "Parigi e Île-de-France"), ("IT", "Italia"), ("REMOTO", "Da remoto"),
           ("FR", "Francia, città non indicata"), ("EU", "Altre sedi in Europa"),
           ("ND", "Sede non indicata"), ("ALTRO", "Fuori Europa")]

# Paesi e città europee (per la sezione "Altre sedi in Europa"); fuori Europa resta nascosto
RE_EUROPA = re.compile(
    r"(?i)\b(france|francia|frankreich|spain|espa[ñn]a|spagna|espagne|spanien|portugal|portogallo|"
    r"germany|deutschland|germania|allemagne|austria|[öo]sterreich|autriche|switzerland|schweiz|suisse|"
    r"svizzera|belgium|belgique|belgi[eë]|belgio|netherlands|nederland|the netherlands|pays[- ]bas|"
    r"paesi bassi|holland|luxembourg|lussemburgo|ireland|irlanda|irlande|united kingdom|uk|england|"
    r"scotland|wales|great britain|regno unito|royaume[- ]uni|denmark|danmark|danimarca|sweden|sverige|"
    r"svezia|norway|norge|norvegia|finland|suomi|finlandia|iceland|poland|polska|polonia|pologne|"
    r"czech republic|czechia|[čc]esko|repubblica ceca|slovakia|slovensko|hungary|magyarorsz[áa]g|"
    r"ungheria|romania|rom[âa]nia|roumanie|bulgaria|greece|hellas|grecia|gr[èe]ce|croatia|hrvatska|"
    r"slovenia|slovenija|estonia|latvia|lithuania|malta|cyprus|cipro|monaco|serbia|"
    r"madrid|barcelona|barcellona|valencia|sevilla|seville|bilbao|zaragoza|m[áa]laga|lisbon|lisboa|"
    r"porto|berlin|berlino|munich|m[üu]nchen|monaco di baviera|hamburg|frankfurt|cologne|k[öo]ln|"
    r"stuttgart|d[üu]sseldorf|darmstadt|bremen|dresden|vienna|wien|z[üu]rich|geneva|gen[èe]ve|ginevra|"
    r"lausanne|basel|bern|brussels|bruxelles|brussel|bruxelas|antwerp|antwerpen|ghent|gent|leuven|li[èe]ge|"
    r"amsterdam|rotterdam|the hague|den haag|eindhoven|delft|utrecht|leiden|noordwijk|dublin|london|"
    r"londra|londres|manchester|cambridge|oxford|edinburgh|bristol|copenhagen|k[øo]benhavn|stockholm|"
    r"gothenburg|g[öo]teborg|oslo|helsinki|warsaw|warszawa|krak[óo]w|prague|praha|praga|budapest|"
    r"bucharest|bucure[șs]ti|sofia|athens|athina|atene|zagreb|ljubljana|tallinn|riga|vilnius|"
    r"lyon|toulouse|marseille|bordeaux|nantes|lille|nice|sophia[- ]antipolis|grenoble|montpellier|"
    r"strasbourg|rennes|brest|cannes|aix[- ]en[- ]provence|pessac|m[ée]rignac|valence|valbonne|"
    r"elancourt|cholet|toulon|orl[ée]ans|tours|dijon|rouen|caen|le mans|angers|clermont[- ]ferrand)\b")


PAESI_EUROPA = set("AT BE BG HR CY CZ DK EE FI FR DE GR EL HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE "
                   "GB UK CH NO IS LI".split())
RE_FUORI_EUROPA = re.compile(
    r"(?i)\b(brazil|brasil|united states|usa|u\.s\.|canada|mexico|m[ée]xico|argentina|chile|colombia|"
    r"peru|india|china|japan|singapore|australia|new zealand|south africa|morocco|maroc|tunisia|tunisie|"
    r"egypt|turkey|t[üu]rkiye|israel|uae|emirates|saudi|qatar|korea|taiwan|vietnam|thailand|malaysia|"
    r"indonesia|philippines|latam|north america|apac|americas)\b")


def luogo(o: dict) -> str:
    """PAR / IT / REMOTO / FR / ND / ALTRO. Parigi vince su tutto: un annuncio
    "Paris / Milano" finisce sotto Parigi. "France" senza città → FR (può
    essere Parigi: si mostra a parte)."""
    loc, paese = o.get("location") or "", (o.get("paese") or "").upper()
    if not loc and not paese:
        # Pagine carriere: la sede è spesso nel testo del link ("… Rome Italy")
        loc = " ".join(m.group(0) for r in (RE_PARIGI, RE_ITALIA) for m in r.finditer(o.get("titolo") or ""))
    if RE_PARIGI.search(loc):
        return "PAR"
    if paese == "IT" or RE_ITALIA.search(loc):
        return "IT"
    if o.get("remoto") or RE_REMOTO.search(loc) or RE_REMOTO_TITOLO.search(o.get("titolo") or ""):
        # Remoto "dal Brasile" o "dagli USA" non serve: solo Europa o paese non indicato
        if (paese and paese not in PAESI_EUROPA) or RE_FUORI_EUROPA.search(loc):
            return "ALTRO"
        return "REMOTO"
    if not loc and not paese:
        return "ND"
    resto = re.sub(r"[\s,;/|()\-]+", "", RE_FRANCIA.sub("", loc))
    if (RE_FRANCIA.search(loc) or paese == "FR") and not resto:
        return "FR"
    if RE_FUORI_EUROPA.search(loc) or (paese and paese not in PAESI_EUROPA):
        return "ALTRO"
    if paese in PAESI_EUROPA or RE_EUROPA.search(loc):
        return "EU"
    return "ALTRO"


def url_pubblico(fonte: dict) -> str:
    """Pagina pubblica con tutti gli annunci della fonte (link "vedi tutte")."""
    t, s = fonte.get("tipo"), fonte.get("slug")
    return {"lever": f"https://jobs.{'eu.' if fonte.get('eu') else ''}lever.co/{s}",
            "greenhouse": f"https://boards.greenhouse.io/{s}",
            "workable": f"https://apply.workable.com/{s}/",
            "smartrecruiters": f"https://jobs.smartrecruiters.com/{s}",
            "ashby": f"https://jobs.ashbyhq.com/{s}",
            "recruitee": f"https://{s}.recruitee.com/",
            "personio": f"https://{s}.{fonte.get('dominio', 'jobs.personio.de')}/",
            "wttj": f"https://www.welcometothejungle.com/fr/companies/{s}/jobs",
            }.get(t) or fonte.get("url") or ""


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
    "in", "und", "y", "da", "do", "eu", "new", "smart", "green", "data", "labs", "lab",
    # paesi (non distinguono un'azienda: "ENGIE Italia" è Engie)
    "italy", "spain", "espana", "germany", "deutschland", "belgium", "belgique", "netherlands",
    "nederland", "hellas", "greece", "portugal", "austria", "ireland", "uk", "suisse", "schweiz",
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


def _distintive(nome):
    tutte = parole(nome)
    return [w for w in tutte if w not in GENERICHE] or tutte


def nome_corrisponde(nostro: str, loro: str) -> bool:
    """Il nome restituito dal portale è compatibile con quello in lista?
    Tutte le parole distintive del loro nome devono comparire nel nostro e la
    prima deve coincidere ("Innova" ≠ "Innovaphone", "Space Applications" ≠
    "Space Programs"). Un nome più corto del nostro ("Alliance" per "Alliance
    Europeenne De Recherche…") è solo compatibile: serve anche il controllo
    del paese (vedi annunci_nei_paesi)."""
    a, b = _distintive(nostro), _distintive(loro)
    if not a or not b:
        return False
    if "".join(a) == "".join(b):
        return True
    return a[0] == b[0] and set(b) <= set(parole(nostro))


def nome_uguale(nostro: str, loro: str) -> bool:
    """Nomi identici parola per parola (generiche comprese): "Trust-It Services"
    non è uguale a "Trust", "Hydrogen Europe Research" non è "Hydrogen"."""
    return bool(parole(nostro)) and "".join(parole(nostro)) == "".join(parole(loro))


def nome_forte(nostro: str, loro: str) -> bool:
    """Il nome sul portale contiene TUTTE le parole distintive del nostro
    ("RINA" per "Rina Consulting SPA" sì; "Magellan" per "Magellan Circle" no)."""
    a = _distintive(nostro)
    return bool(a) and set(a) <= set(parole(loro))


def testo_cita_nome(nostro: str, testi: list) -> bool:
    """Per i portali che non danno il nome dell'azienda (Lever, Ashby): il nome
    completo (parole distintive) deve comparire nel testo degli annunci."""
    a = _distintive(nostro)
    if not a:
        return False
    frase = r"\b" + r"[\s\-]*".join(map(re.escape, a[:4])) + r"\b"
    return any(re.search(frase, _ascii(t)) for t in testi if t)


# Paesi delle aziende in lista (codici CORDIS) → nomi e città principali
PAESI_RE = {k: re.compile(r"\b(" + v + r")\b", re.I) for k, v in {
    "FR": r"france|francia|paris|lyon|marseille|toulouse|bordeaux|lille|nantes|strasbourg|montpellier|"
          r"rennes|grenoble|nice|sophia[- ]antipolis|brest|cannes|aix[- ]en[- ]provence|[ée]lancourt|v[ée]lizy|"
          r"massy|saclay|la d[ée]fense|cergy|gennevilliers|valence|orl[ée]ans|tours|pau|metz|nancy|dijon|caen",
    "IT": r"ital(y|ia|ie|ien)|milan[oe]?|rom[ae]|turin|torino|genova|genoa|bologna|firenze|florence|napoli|"
          r"naples|padova|venezia|venice|verona|bari|pisa|trento|trieste|bergamo|brescia|modena|parma|"
          r"cagliari|palermo|catania|lecce|ancona|perugia|pescara|udine|la spezia|fano|ivrea|siena",
    "ES": r"spain|espa[ñn]a|espagne|spagna|madrid|barcelona|valencia|sevilla|seville|bilbao|zaragoza|"
          r"m[áa]laga|pamplona|san sebasti[áa]n|donostia|vigo|a coru[ñn]a|valladolid|granada|murcia|santander",
    "DE": r"germany|deutschland|allemagne|germania|berlin|munich|m[üu]nchen|hamburg|frankfurt|cologne|"
          r"k[öo]ln|stuttgart|d[üu]sseldorf|dresden|leipzig|hannover|bremen|karlsruhe|aachen|bonn|darmstadt",
    "BE": r"belgium|belgique|belgi[eë]|belgio|brussels|bruxelles|brussel|antwerp|antwerpen|anvers|ghent|gent|"
          r"li[èe]ge|leuven|louvain|namur|mons|charleroi|mechelen|hasselt",
    "NL": r"netherlands|nederland|pays[- ]bas|paesi bassi|holland|amsterdam|rotterdam|the hague|den haag|"
          r"utrecht|eindhoven|delft|leiden|groningen|rijswijk|enschede|nijmegen|wageningen",
    "EL": r"greece|hellas|gr[eè]ce|grecia|athens|ath[iè]nes|atene|thessaloniki|patras|heraklion|larissa|volos",
    "UK": r"united kingdom|\buk\b|england|scotland|wales|great britain|london|manchester|edinburgh|bristol|"
          r"cambridge|oxford|birmingham|glasgow|leeds|belfast|cardiff|newcastle|reading|sheffield",
    "PT": r"portugal|portogallo|lisbon|lisboa|porto|oporto|coimbra|braga|aveiro|faro",
    "AT": r"austria|[öo]sterreich|autriche|vienna|wien|graz|linz|salzburg|innsbruck",
    "IE": r"ireland|irlanda|irlande|dublin|cork|galway|limerick",
    "CY": r"cyprus|chypre|cipro|nicosia|limassol|larnaca",
    "CH": r"switzerland|schweiz|suisse|svizzera|zurich|z[üu]rich|geneva|gen[èe]ve|ginevra|basel|bern|lausanne|lugano",
    "RO": r"romania|roumanie|bucharest|bucure[șs]ti|cluj|timi[șs]oara|ia[șs]i|bra[șs]ov",
    "DK": r"denmark|danmark|danemark|danimarca|copenhagen|k[øo]benhavn|aarhus|odense|aalborg",
    "SE": r"sweden|sverige|su[èe]de|svezia|stockholm|gothenburg|g[öo]teborg|malm[öo]|uppsala|lund|link[öo]ping",
    "BG": r"bulgaria|bulgarie|sofia|plovdiv|varna",
    "FI": r"finland|suomi|finlande|finlandia|helsinki|espoo|tampere|oulu|turku",
    "NO": r"norway|norge|norv[èe]ge|norvegia|oslo|bergen|trondheim|stavanger",
    "SI": r"slovenia|slov[ée]nie|ljubljana|maribor",
    "CZ": r"czech|czechia|[čc]esko|r[ée]publique tch[èe]que|prague|praha|brno|ostrava",
    "HU": r"hungary|magyarorsz[áa]g|hongrie|ungheria|budapest|debrecen|szeged",
    "PL": r"poland|polska|pologne|polonia|warsaw|warszawa|krak[óo]w|wroc[łl]aw|pozna[ńn]|gda[ńn]sk|[łl][óo]d[źz]",
    "HR": r"croatia|hrvatska|croatie|zagreb|split|rijeka",
    "EE": r"estonia|eesti|tallinn|tartu",
    "SK": r"slovakia|slovensko|slovaquie|bratislava|ko[šs]ice",
    "LU": r"luxembourg|lussemburgo",
    "LT": r"lithuania|lietuva|vilnius|kaunas",
    "RS": r"serbia|srbija|belgrade|beograd|novi sad",
    "MT": r"malta|valletta",
    "LV": r"latvia|latvija|riga",
    "MK": r"north macedonia|macedonia|skopje",
}.items()}
ISO = {"UK": "GB", "EL": "GR"}


def annunci_nei_paesi(offerte: list, codici: list) -> bool:
    """Almeno un annuncio è in uno dei paesi dell'azienda (codici CORDIS)."""
    attesi = {c.upper() for c in codici if c}
    iso = attesi | {ISO[c] for c in attesi if c in ISO}
    for o in offerte:
        if (o.get("paese") or "").upper() in iso:
            return True
        testo = (o.get("location") or "")
        if any(PAESI_RE[c].search(testo) for c in attesi if c in PAESI_RE):
            return True
    return False


def _prova(tipo, slug, azienda):
    """Fonte se lo slug esiste ED è dell'azienda della lista, altrimenti None.
    Due controlli: il nome (dal portale o citato negli annunci) e il paese
    (almeno un annuncio in uno dei paesi dell'azienda). Senza annunci da
    controllare si accetta solo il nome identico."""
    rapido = dict(rapida=True, timeout=8)
    nome, paesi = azienda["n"], (azienda.get("p") or "").split(",")
    offerte_pronte = None
    try:
        if tipo == "greenhouse":
            loro = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}", **rapido).get("name", "")
        elif tipo == "workable":
            loro = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", **rapido).get("name", "")
        elif tipo == "smartrecruiters":
            b = _json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 1}, **rapido)
            loro = ((b.get("content") or [{}])[0].get("company") or {}).get("name", "")
        elif tipo == "recruitee":
            b = _json(f"https://{slug}.recruitee.com/api/offers/", **rapido)
            loro = ((b.get("offers") or [{}])[0]).get("company_name", "")
        elif tipo in ("lever", "lever-eu"):
            b = _json(f"https://{'api.eu' if tipo == 'lever-eu' else 'api'}.lever.co/v0/postings/{slug}?mode=json", **rapido)
            testi = [j.get("descriptionPlain", "") + " " + j.get("additionalPlain", "") for j in b[:30]]
            loro = nome if (b and testo_cita_nome(nome, testi)) else ""
        elif tipo == "ashby":
            b = _json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", **rapido)
            testi = [j.get("descriptionPlain", "") for j in (b.get("jobs") or [])[:30]]
            loro = nome if testo_cita_nome(nome, testi) else ""
        elif tipo == "wttj":
            # Con il browser: alle richieste dirette WTTJ risponde 202 (pagina anti-bot)
            html = _html_con_browser(f"https://www.welcometothejungle.com/fr/companies/{slug}/jobs")
            if not html:
                return None
            loro = next((n for n in nomi_pagina_wttj(html) if nome_corrisponde(nome, n)), "")
            offerte_pronte = _wttj_estrai(slug, html)
        else:
            return None
        if not loro or not nome_corrisponde(nome, loro):
            return None
        f = {"tipo": "lever" if tipo == "lever-eu" else tipo, "slug": slug}
        if tipo == "lever-eu":
            f["eu"] = True
        offerte = offerte_pronte if offerte_pronte is not None else leggi_fonte(f)
        nei_paesi = bool(offerte) and annunci_nei_paesi(offerte, paesi)
        forte = nome_forte(nome, loro)
        if forte and nei_paesi:
            f["verifica"] = f"nome '{loro}' + annunci in {'/'.join(p for p in paesi if p)}"
        elif forte and not offerte and nome_uguale(nome, loro) and tipo not in ("lever", "lever-eu", "ashby"):
            # Nome identico ma niente annunci per controllare il paese: non verificabile
            # ("GAC" su Workable può essere qualunque GAC). Si riprova la settimana dopo.
            f["da_verificare"] = f"nome identico '{loro}' ma nessun annuncio per controllare il paese"
        elif nei_paesi:
            # Nome solo compatibile (es. "Thales" per "Thales Six Gts France"): può
            # essere il gruppo o un omonimo. Non si usa: va verificato a mano.
            f["da_verificare"] = f"nome '{loro}' più corto + annunci in {'/'.join(p for p in paesi if p)}"
        else:
            return None
        return f
    except (FonteErrore, ValueError, AttributeError, TypeError, IndexError, KeyError):
        return None


def nomi_pagina_wttj(html):
    """Nomi candidati dell'azienda in una pagina WTTJ: titolo, og:title, h1."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    grezzi = [soup.title.get_text() if soup.title else ""]
    grezzi += [m.get("content", "") for m in soup.find_all("meta", property="og:title")]
    grezzi += [h.get_text(" ", strip=True) for h in soup.find_all("h1")[:2]]
    nomi = []
    for g in grezzi:
        g = re.sub(r"(?i)^(offres d.emploi|jobs?|emplois?)\s*(chez|at|[-:])?\s*", "", g.strip())
        for pezzo in re.split(r"\s[\|:–-]\s", g):
            if pezzo.strip() and "welcome to the jungle" not in pezzo.lower():
                nomi.append(pezzo.strip())
    return list(dict.fromkeys(nomi))


TIPI_SCOPERTA = ["greenhouse", "lever", "lever-eu", "workable", "smartrecruiters", "ashby", "recruitee"]


def scopri(azienda: dict) -> list:
    """Fonti per un'azienda della lista, provando gli slug sui portali. WTTJ solo
    per le aziende con sede in Francia. Le fonti con "da_verificare" non vanno
    nella newsletter finché non le conferma una persona."""
    # WTTJ richiede il browser (lento): solo aziende francesi del focus Parigi
    francese = "FR" in (azienda.get("p") or "").split(",")
    tipi = TIPI_SCOPERTA + (["wttj"] if francese and "PAR" in (azienda.get("k") or "") else [])
    trovate, usati = [], set()
    for tipo in tipi:
        slugs = slug_candidati(azienda["n"])
        if tipo == "wttj":                    # su WTTJ gli slug hanno i trattini
            slugs = [x for x in slugs if "-" in x or len(parole(azienda["n"])) == 1][:2]
        for slug in slugs:
            f = _prova(tipo, slug, azienda)
            if f and f["tipo"] not in usati:
                trovate.append(f)
                if "da_verificare" not in f:
                    usati.add(f["tipo"])
                    break
    return trovate
