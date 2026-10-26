# ============================================================
#  🎯 NEWSLETTER AZIENDE TARGET EUROPA
#  Offerte di lavoro delle aziende della lista "Aziende Target Europa"
#  (dati/aziende.json), con priorità Parigi/Île-de-France e Italia.
#
#  Fonti per azienda: dati/fonti_manuali.json (scritte a mano, vincono)
#  + dati/fonti.json (trovate da scopri_fonti.py).
#  Storico delle offerte già inviate: dati/seen.json
# ============================================================

import hashlib
import html as html_lib
import json
import os
import re
import sys
import smtplib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import fonti as tf

DIR = "dati"
AZIENDE_FILE = os.path.join(DIR, "aziende.json")
FONTI_FILE = os.path.join(DIR, "fonti.json")
FONTI_MANUALI_FILE = os.path.join(DIR, "fonti_manuali.json")
SEEN_FILE = os.path.join(DIR, "seen.json")

# Offerte "nuove" ma pubblicate da più di questi giorni: non si mostrano
MAX_GIORNI_NUOVA = 30
# Un ID non più visto da tanti giorni (offerta chiusa) esce dallo storico
GIORNI_OBLIO = 90
# Offerte mostrate al massimo per azienda in una email (le altre: link)
MAX_PER_AZIENDA = 12
# Sezioni mostrate: le offerte in "ALTRO" (fuori da Parigi/Italia, non da
# remoto) si contano ma non si mostrano. Obiettivo: Parigi, poi Italia.
SEZIONI_MOSTRATE = {"PAR", "IT", "REMOTO", "FR", "ND"}
# Gmail taglia i messaggi oltre ~102 KB ("[Messaggio troncato]"): si riducono
# le offerte mostrate per azienda finché l'email sta sotto questo limite.
MAX_EMAIL_BYTES = 95_000
STORICO_MAX_RUN = 14

ETICHETTE_LIVELLO = [
    ("Stage", r"\b(stage|stagiaire|intern(ship)?|tirocini[oa]|alternan\w*|apprenti\w*|"
              r"v\.?i\.?e\.?|working student|werkstudent)\b"),
    ("Junior", r"\b(junior|jr\.?|graduate|neolaureat[oie]|entry[ -]level|d[ée]butant)\b"),
    ("Manager", r"\b(manager|director|directeur|directrice|partner|head of|lead)\b"),
    ("Senior", r"\b(senior|sr\.?|experienced|confirm[ée]e?)\b"),
]


# ------------------------------------------------------------
#  Dati
# ------------------------------------------------------------

def _leggi_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def carica_aziende():
    dati = _leggi_json(AZIENDE_FILE, None)
    if not dati or not dati.get("aziende"):
        raise SystemExit(f"❌ {AZIENDE_FILE} mancante o vuoto: lancia importa_aziende.py")
    return {a["id"]: a for a in dati["aziende"]}


def carica_fonti(aziende):
    """{id azienda: [fonti]}. Le fonti manuali sostituiscono quelle automatiche
    della stessa azienda. Gli ID che non sono nella lista vengono ignorati."""
    auto = _leggi_json(FONTI_FILE, {}).get("fonti", {})
    manuali = {k: v for k, v in _leggi_json(FONTI_MANUALI_FILE, {}).items() if not k.startswith("_")}
    fonti = {**auto, **manuali}
    fuori = sorted(k for k in fonti if k not in aziende)
    if fuori:
        print(f"⚠️  Fonti ignorate (aziende non in lista): {', '.join(fuori)}")
    return {k: v for k, v in fonti.items() if k in aziende and v}


def priorita(a):
    """Ordine delle aziende: Parigi, Italia, open innovation, punteggio."""
    k = a.get("k") or ""
    return (-("PAR" in k), -("IT" in k), -(a.get("o") or 0), -(a.get("s") or 0), a["n"].lower())


class SeenIlleggibile(Exception):
    pass


def carica_seen():
    if not os.path.exists(SEEN_FILE):
        return {"ids": {}, "fonti": [], "storico": [], "ultima_run": None}
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("ids"), dict):
            raise ValueError("manca il dizionario 'ids'")
    except Exception as e:
        raise SeenIlleggibile(f"{SEEN_FILE} illeggibile: {e}") from e
    d.setdefault("fonti", [])
    d.setdefault("storico", [])
    return d


def salva_seen(d):
    tmp = SEEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({**d, "ids": dict(sorted(d["ids"].items())), "fonti": sorted(set(d["fonti"])),
                   "storico": d["storico"][-STORICO_MAX_RUN:]}, f, indent=0, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SEEN_FILE)


def job_id(azienda_id, o):
    raw = o.get("url") or f"{azienda_id}|{o.get('titolo', '').lower()}|{o.get('location', '').lower()}"
    return hashlib.md5(raw.strip().encode()).hexdigest()


def eta_giorni(data):
    try:
        return (datetime.now().date() - datetime.strptime(data[:10], "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------
#  Raccolta
# ------------------------------------------------------------

_lock_browser = threading.Lock()
_browser_originale = tf._html_con_browser


def _browser_seriale(url):
    # Playwright: un browser alla volta anche se le fonti girano in parallelo
    with _lock_browser:
        return _browser_originale(url)


def raccogli(aziende, fonti):
    """[(id azienda, fonte, offerte | None, errore)] con ogni fonte letta una
    volta sola: se due aziende della lista condividono un portale (stesso
    gruppo), le offerte vanno alla prima per priorità."""
    tf._html_con_browser = _browser_seriale
    compiti, viste = [], set()
    for aid in sorted(fonti, key=lambda i: priorita(aziende[i])):
        for f in fonti[aid]:
            k = tf.chiave_fonte(f)
            if k not in viste:
                viste.add(k)
                compiti.append((aid, f))

    def uno(c):
        aid, f = c
        try:
            return aid, f, tf.leggi_fonte(f), None
        except tf.FonteErrore as e:
            return aid, f, None, str(e)
        except Exception as e:          # un lettore rotto non deve fermare gli altri
            return aid, f, None, f"{e.__class__.__name__}: {e}"

    with ThreadPoolExecutor(max_workers=8) as ex:
        risultati = list(ex.map(uno, compiti))
    tf._html_con_browser = _browser_originale
    return risultati


def seleziona(aziende, risultati, seen, oggi):
    """Decide cosa mostrare. Restituisce (nuove, statistiche).
    - Fonte mai vista prima: portale strutturato → si mostrano tutte le offerte
      aperte (etichetta "già aperta"); pagina generica → stato iniziale silenzioso.
    - Dopo: si mostra ogni offerta nuova, salvo se datata > MAX_GIORNI_NUOVA."""
    nuove, stat = [], {"trovate": 0, "fuori_focus": 0, "vecchie": 0, "iniziali": 0}
    fonti_note = set(seen["fonti"])
    for aid, f, offerte, err in risultati:
        if offerte is None:
            continue
        k = tf.chiave_fonte(f)
        prima_volta = k not in fonti_note
        for o in offerte:
            stat["trovate"] += 1
            o["luogo"] = tf.luogo(o)
            # Sede non indicata: interessa solo per le aziende con sede a Parigi o in Italia
            if o["luogo"] not in SEZIONI_MOSTRATE or (o["luogo"] == "ND" and not aziende[aid].get("k")):
                stat["fuori_focus"] += 1
                continue
            o["fonte_url"] = tf.url_pubblico(f)
            i = job_id(aid, o)
            gia = i in seen["ids"]
            seen["ids"][i] = oggi
            if gia:
                continue
            eta = eta_giorni(o.get("data"))
            if prima_volta:
                # Prima lettura: le pagine generiche diventano lo stato iniziale
                # (senza date un annuncio non si distingue da un link qualunque);
                # dai portali strutturati si mostrano tutte le offerte aperte.
                if f.get("tipo") == "pagina":
                    stat["iniziali"] += 1
                    continue
                nuove.append({**o, "azienda": aid, "gia_aperta": True})
                continue
            if eta is not None and eta > MAX_GIORNI_NUOVA:
                stat["vecchie"] += 1
                continue
            nuove.append({**o, "azienda": aid})
        seen["fonti"].append(k)
    # Stessa offerta da due portali dello stesso gruppo: una sola volta
    uniche, viste = [], set()
    for o in nuove:
        chiave = (re.sub(r"\W+", " ", o["titolo"].lower()).strip(), o.get("location", "").lower())
        if chiave in viste:
            stat["doppioni"] = stat.get("doppioni", 0) + 1
            continue
        viste.add(chiave)
        uniche.append(o)
    nuove = uniche
    # Oblio: offerte non più viste da GIORNI_OBLIO giorni
    limite = (datetime.strptime(oggi, "%Y-%m-%d") - timedelta(days=GIORNI_OBLIO)).strftime("%Y-%m-%d")
    seen["ids"] = {i: d for i, d in seen["ids"].items() if d >= limite}
    return nuove, stat


def controlli(risultati, storico):
    """Problemi da segnalare: fonti in errore e fonti scese a 0 offerte."""
    problemi = []
    for aid, f, offerte, err in risultati:
        k = tf.chiave_fonte(f)
        passati = [r["conteggi"].get(k) for r in storico if isinstance(r.get("conteggi"), dict)]
        passati = [p for p in passati if isinstance(p, int)]
        if err:
            problemi.append((aid, k, f"non raggiungibile ({err[:120]})"))
        elif not offerte and passati and max(passati) > 0:
            problemi.append((aid, k, f"0 offerte (nelle ultime run fino a {max(passati)})"))
    return problemi


# ------------------------------------------------------------
#  Email
# ------------------------------------------------------------

def etichette(titolo):
    for nome, pat in ETICHETTE_LIVELLO:
        if re.search(pat, titolo or "", re.I):
            return [nome]
    return []


def _quando(data):
    eta = eta_giorni(data)
    if eta is None:
        return ""
    if eta <= 0:
        return "oggi"
    if eta == 1:
        return "ieri"
    if eta < 7:
        return f"{eta} giorni fa"
    return datetime.strptime(data[:10], "%Y-%m-%d").strftime("%d/%m")


def genera_html(nuove, aziende, fonti, stat, problemi, n_fonti, max_per_azienda=MAX_PER_AZIENDA):
    esc = html_lib.escape
    sans = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
    serif = "font-family:Georgia,'Times New Roman',serif;"
    ink, grigio, chiaro, linea, accento = "#111827", "#6b7280", "#9ca3af", "#e5e7eb", "#0E6B6F"
    oggi = datetime.now().strftime("%d/%m/%Y")

    per_sezione = {s: [o for o in nuove if o["luogo"] == s] for s, _ in tf.SEZIONI}
    sommario = " &nbsp;·&nbsp; ".join(
        f'<a href="#s-{s}" style="color:{ink};text-decoration:none;">{esc(nome)}&nbsp;'
        f'<strong>{len(per_sezione[s])}</strong></a>'
        for s, nome in tf.SEZIONI if per_sezione[s])

    corpo = ""
    for s, nome_sez in tf.SEZIONI:
        offerte = per_sezione[s]
        if not offerte:
            continue
        corpo += f"""
      <tr><td id="s-{s}" style="padding:30px 32px 4px;{sans}font-size:13px;font-weight:700;
          letter-spacing:2px;text-transform:uppercase;color:{ink};border-bottom:2px solid {ink};">
          {esc(nome_sez)} <span style="color:{chiaro};font-weight:400;">· {len(offerte)}</span></td></tr>"""
        per_az = {}
        for o in offerte:
            per_az.setdefault(o["azienda"], []).append(o)
        for aid in sorted(per_az, key=lambda i: priorita(aziende[i])):
            a = aziende[aid]
            chips = []
            if a.get("c") == "A":
                chips.append("classe A")
            if a.get("o"):
                chips.append("open innovation")
            if a.get("k"):
                chips.append({"PAR": "sede Parigi", "IT": "sede Italia", "IT+PAR": "Parigi + Italia"}
                             .get(a["k"], a["k"]))
            lista = sorted(per_az[aid], key=lambda o: (eta_giorni(o.get("data")) is None,
                                                       eta_giorni(o.get("data")) or 0))
            voci = ""
            for o in lista[:max_per_azienda]:
                meta = [esc(x) for x in (o.get("location"), _quando(o.get("data"))) if x]
                meta += [f'<span style="padding:0 6px;border:1px solid {linea};border-radius:9px;'
                         f'font-size:11px;">{e}</span>' for e in etichette(o["titolo"])]
                if o.get("gia_aperta"):
                    meta.append(f'<span style="color:{chiaro};">già aperta</span>')
                voci += f"""
            <tr><td style="padding:9px 0 9px 12px;border-left:2px solid {linea};">
              <a href="{esc(o.get('url') or '#')}" style="{serif}font-size:16px;line-height:1.35;
                 color:{ink};text-decoration:none;">{esc(o['titolo'] or 'Annuncio')}</a>
              <div style="margin-top:3px;{sans}font-size:12px;color:{grigio};">
                {' &nbsp;·&nbsp; '.join(meta)}</div></td></tr>"""
            extra = len(lista) - max_per_azienda
            if extra > 0:
                link = next((o["fonte_url"] for o in lista if o.get("fonte_url")), "")
                voci += (f'<tr><td style="padding:6px 0 6px 12px;{sans}font-size:12px;color:{grigio};">'
                         f'+ altre {extra} offerte' + (f' · <a href="{esc(link)}" style="color:{ink};">'
                                                      f'vedi tutte</a>' if link else "") + '</td></tr>')
            corpo += f"""
      <tr><td style="padding:18px 32px 0;">
        <div style="{sans}font-size:15px;font-weight:700;color:{ink};">{esc(a['n'])}</div>
        <div style="{sans}font-size:11px;color:{accento};margin:2px 0 6px;">{esc(' · '.join(chips))}</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{voci}</table>
      </td></tr>"""

    avviso = ""
    if problemi:
        righe = "".join(f"<div>· <strong>{esc(aziende[a]['n'])}</strong> ({esc(k.split(':')[0])}): "
                        f"{esc(m)}</div>" for a, k, m in problemi[:15])
        if len(problemi) > 15:
            righe += f"<div>· … e altre {len(problemi) - 15}</div>"
        avviso = f"""
      <tr><td style="padding:16px 32px 0;"><div style="border-left:3px solid #f59e0b;
          padding:4px 0 4px 14px;{sans}font-size:12px;line-height:1.5;color:#92400e;">
          <strong>Fonti da controllare</strong>{righe}</div></td></tr>"""

    totale = len(nuove)
    aperte = sum(1 for o in nuove if o.get("gia_aperta"))
    titolo = (f"{totale} nuov{'a offerta' if totale == 1 else 'e offerte'}" if totale
              else "Nessuna offerta nuova")
    if aperte:
        titolo = (f"{totale} offerte" + (f", di cui {aperte} già aperte" if aperte < totale
                                          else " già aperte"))
    aziende_con_fonte = len(fonti)
    nota_taglio = (f" Per restare leggibile l'email mostra al massimo {max_per_azienda} offerte per "
                   "azienda e sezione: le altre sono nel link «vedi tutte»."
                   if any(sum(1 for o in nuove if o["azienda"] == a and o["luogo"] == l) > max_per_azienda
                          for a, l in {(o["azienda"], o["luogo"]) for o in nuove}) else "")
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"></head>
<body style="margin:0;padding:0;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#ffffff">
  <tr><td align="center" style="padding:16px 0 32px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;">
      <tr><td style="padding:24px 32px 18px;border-bottom:2px solid {ink};">
        <div style="{sans}font-size:12px;font-weight:700;letter-spacing:3px;color:{accento};">AZIENDE TARGET EUROPA</div>
        <div style="{sans}font-size:12px;color:{grigio};">{oggi} · Parigi, Italia, da remoto</div>
        <div style="margin-top:16px;{serif}font-size:30px;line-height:1.15;color:{ink};">{titolo}</div>
        <div style="margin-top:12px;{sans}font-size:14px;line-height:1.7;">{sommario}</div>
      </td></tr>{avviso}{corpo}
      <tr><td style="padding:34px 32px 0;"><div style="border-top:1px solid {linea};padding-top:12px;
          {sans}font-size:11px;line-height:1.6;color:{chiaro};">
        Solo aziende della lista Aziende Target Europa ({len(aziende)} aziende, {aziende_con_fonte} con una
        fonte di annunci, {n_fonti} fonti lette). {stat['trovate']} offerte lette oggi, di cui
        {stat['fuori_focus']} fuori da Parigi/Italia/remoto (non mostrate).
        Livello (Stage, Junior…) dedotto dal titolo.{nota_taglio}</div></td></tr>
    </table>
  </td></tr>
</table></body></html>"""


def componi_email(nuove, aziende, fonti, stat, problemi, n_fonti):
    """HTML sotto MAX_EMAIL_BYTES: se serve, meno offerte per azienda."""
    for massimo in (MAX_PER_AZIENDA, 8, 5, 3, 2, 1):
        html = genera_html(nuove, aziende, fonti, stat, problemi, n_fonti, massimo)
        if len(html.encode("utf-8")) <= MAX_EMAIL_BYTES:
            break
    print(f"✉️  Email: {len(html.encode('utf-8')) // 1024} KB, max {massimo} offerte per azienda e sezione")
    return html


def invia_email(html_body, oggetto_email):
    """Invio via Gmail (App Password). Destinatari in CCN: nell'intestazione
    compare solo il mittente. Restituisce 'ok', 'auth', 'config' o 'errore'."""
    mittente = os.environ.get("GMAIL_MITTENTE", "")
    password = os.environ.get("GMAIL_PASSWORD", "")
    dest = os.environ.get("EMAIL_DESTINATARIO", "")
    if not mittente or not password or not dest:
        print("❌ Secret mancanti: GMAIL_MITTENTE, GMAIL_PASSWORD, EMAIL_DESTINATARIO")
        return "config"
    destinatari = list(dict.fromkeys(d for d in re.split(r"[,;\s]+", dest) if d))
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = oggetto_email, mittente, mittente
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    for tentativo, attesa in enumerate((0, 10, 30), 1):
        time.sleep(attesa)
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
                s.login(mittente, password)
                s.sendmail(mittente, list(dict.fromkeys([mittente] + destinatari)), msg.as_string())
            print(f"✅ Email inviata a {len(destinatari)} destinatari (CCN)")
            return "ok"
        except smtplib.SMTPAuthenticationError:
            print("❌ Autenticazione Gmail rifiutata: rigenera la App Password")
            return "auth"
        except Exception as e:
            print(f"❌ Invio fallito (tentativo {tentativo}/3): {e}")
    return "errore"


def oggetto(nuove):
    n = len(nuove)
    par = sum(o["luogo"] == "PAR" for o in nuove)
    it = sum(o["luogo"] == "IT" for o in nuove)
    tipo = "offerte" if any(o.get("gia_aperta") for o in nuove) else f"nuov{'a' if n == 1 else 'e'}"
    return f"🎯 Aziende Target {datetime.now():%d/%m/%Y} — {n} {tipo} (Parigi {par} · Italia {it})"


# ------------------------------------------------------------
#  Main
# ------------------------------------------------------------

def prova(solo_ids=None, dubbi=False):
    """Legge le fonti e stampa cosa trova, senza email e senza toccare lo
    storico. Serve a verificare fonti nuove o sospette (workflow prova-fonti).
    dubbi=True legge invece i candidati "da_verificare" (per deciderli a mano)."""
    aziende = carica_aziende()
    if dubbi:
        fonti = {k: v for k, v in _leggi_json(FONTI_FILE, {}).get("da_verificare", {}).items() if k in aziende}
    else:
        fonti = carica_fonti(aziende)
    if solo_ids:
        fonti = {k: v for k, v in fonti.items() if k in solo_ids}
    print(f"🧪 PROVA FONTI: {len(fonti)} aziende\n")
    ok = 0
    for aid, f, offerte, err in sorted(raccogli(aziende, fonti), key=lambda r: priorita(aziende[r[0]])):
        print(f"■ {aziende[aid]['n']} [{aid}] · {tf.chiave_fonte(f)}")
        if err:
            print(f"   ❌ {err}")
            continue
        ok += 1
        conta = {}
        for o in offerte:
            o["luogo"] = tf.luogo(o)
            conta[o["luogo"]] = conta.get(o["luogo"], 0) + 1
        print(f"   ✅ {len(offerte)} offerte · " + ", ".join(f"{k} {v}" for k, v in sorted(conta.items())))
        for o in ([o for o in offerte if o["luogo"] in SEZIONI_MOSTRATE] or offerte)[:5]:
            print(f"      - {o['titolo'][:70]} | {o['location'][:30]} | {o['data']} | {o['url'][:80]}")
    print(f"\n🧪 {ok} fonti funzionanti su {sum(len(v) for v in fonti.values())}")


def main():
    if "--prova" in sys.argv:
        ids = [a for a in sys.argv[1:] if not a.startswith("--")]
        return prova(set(ids) or None, dubbi="--dubbi" in sys.argv)
    oggi = datetime.now().strftime("%Y-%m-%d")
    print(f"\n🎯 NEWSLETTER AZIENDE TARGET  {datetime.now():%d/%m/%Y %H:%M}\n")
    try:
        seen = carica_seen()
    except SeenIlleggibile as e:
        print(f"❌ {e}\n   Run interrotta: senza storico tutte le offerte risulterebbero nuove.")
        sys.exit(1)
    forza = os.environ.get("NEWSLETTER_FORZA", "").strip().lower() in ("1", "true", "yes", "si", "sì")
    if not forza and seen.get("ultima_run") == oggi:
        print(f"✅ Run di oggi ({oggi}) già fatta: niente da fare.")
        return

    aziende = carica_aziende()
    fonti = carica_fonti(aziende)
    print(f"📋 {len(aziende)} aziende in lista · {len(fonti)} con almeno una fonte")
    if not fonti:
        print("⚠️  Nessuna fonte configurata: lancia scopri_fonti.py o compila fonti_manuali.json")
        return

    risultati = raccogli(aziende, fonti)
    for aid, f, offerte, err in risultati:
        stato = f"❌ {err}" if err else f"{len(offerte)} offerte"
        print(f"   {aziende[aid]['n'][:40]:40s} {tf.chiave_fonte(f)[:45]:45s} {stato}")

    problemi = controlli(risultati, seen["storico"])
    nuove, stat = seleziona(aziende, risultati, seen, oggi)
    seen["storico"].append({"data": oggi, "conteggi": {
        tf.chiave_fonte(f): (len(o) if o is not None else None) for _, f, o, _ in risultati}})
    print(f"\n📊 {stat['trovate']} offerte · {len(nuove)} nuove da mostrare · "
          f"{stat['fuori_focus']} fuori focus · {stat['vecchie']} vecchie · "
          f"{stat['iniziali']} stato iniziale (prima lettura della fonte)")
    for a, k, m in problemi:
        print(f"   🟠 {aziende[a]['n']} [{k}]: {m}")

    errori = sum(1 for r in risultati if r[3])
    rete_ko = errori > len(risultati) / 2

    stato_invio = "nessuna"
    controllo_settimanale = datetime.now().weekday() == 0 and problemi
    if nuove or controllo_settimanale:
        html = componi_email(nuove, aziende, fonti, stat, problemi, len(risultati))
        ogg = oggetto(nuove) if nuove else \
            f"🎯 Aziende Target {datetime.now():%d/%m/%Y} — nessuna novità, {len(problemi)} fonti da controllare"
        stato_invio = invia_email(html, ogg)
    else:
        print("📭 Nessuna offerta nuova: email non inviata")

    if stato_invio in ("ok", "nessuna") and not rete_ko:
        seen["ultima_run"] = oggi
        salva_seen(seen)
        print(f"💾 Storico salvato ({len(seen['ids'])} offerte)")
    else:
        print("⚠️  Storico NON aggiornato: le offerte di oggi verranno riproposte")

    motivi = []
    if stato_invio in ("auth", "config", "errore"):
        motivi.append(f"invio email: {stato_invio}")
    if rete_ko:
        motivi.append(f"{errori} fonti su {len(risultati)} non raggiungibili")
    if motivi:
        print("❌ Run FALLITA: " + "; ".join(motivi))
        sys.exit(1)


if __name__ == "__main__":
    main()
