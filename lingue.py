"""
Filtro lingua: esclude le offerte che chiedono una lingua che Fra non parla.

Fra parla italiano, inglese e spagnolo; francese di base. Si esclude un'offerta se:
- il testo dell'annuncio è scritto in una lingua non parlata, francese compreso (es. tutto in
  tedesco o tutto in francese; senza descrizione si guarda il titolo), oppure
- chiede esplicitamente una lingua non parlata ("fluent German", "Deutsch fließend",
  "néerlandais courant"…), salvo quando è facoltativa ("a plus", "un atout") o in
  alternativa a una lingua parlata ("English or German").
Un annuncio in inglese che chiede ANCHE francese fluente non si esclude: è segnalato
nell'email (deciso dall'utente: esclusi solo gli annunci tutti in francese).
Senza testo (descrizione non leggibile) l'offerta resta: meglio un annuncio in più
che uno buono perso.
"""
import re

PARLATE = {"it", "en", "es"}
SEGNALATE = {"fr"}          # parlata a livello base: si segnala, non si esclude

NOMI = {
    "fr": "francese", "de": "tedesco", "nl": "olandese", "pt": "portoghese", "el": "greco",
    "pl": "polacco", "sv": "svedese", "da": "danese", "no": "norvegese", "fi": "finlandese",
    "cs": "ceco", "sk": "slovacco", "hu": "ungherese", "ro": "rumeno", "bg": "bulgaro",
    "hr": "croato", "sl": "sloveno", "lt": "lituano", "lv": "lettone", "et": "estone",
    "ru": "russo", "uk": "ucraino", "ar": "arabo", "zh": "cinese", "ja": "giapponese",
    "ko": "coreano", "tr": "turco", "he": "ebraico",
    "it": "italiano", "en": "inglese", "es": "spagnolo",
}

# Nomi delle lingue in inglese, francese, italiano, spagnolo, tedesco, olandese
_NOMI_RE = {
    "fr": r"french|fran[cç]ais(?:e)?|francese|franc[eé]s(?:a)?|franz[öo]sisch\w*|frans(?:e)?",
    "de": r"german|deutsch\w*|allemand(?:e)?|tedesco|alem[aá]n(?:a)?|duits(?:e)?",
    "nl": r"dutch|nederlands(?:e)?|n[ée]erlandais(?:e)?|olandese|neerland[ée]s(?:a)?|flemish|"
          r"flamand(?:e)?|fiammingo|niederl[äa]ndisch\w*|vlaams(?:e)?",
    "pt": r"portuguese|portugais(?:e)?|portoghese|portugu[eé]s(?:a)?|portugiesisch\w*|portugees",
    "el": r"greek|grec(?:que)?|greco|griego|griechisch\w*|grieks",
    "pl": r"Polish|polonais(?:e)?|polacco|polaco|polnisch\w*|pools(?:e)?",
    "sv": r"swedish|su[ée]dois(?:e)?|svedese|sueco|schwedisch\w*|zweeds",
    "da": r"danish|danois(?:e)?|danese|dan[ée]s(?:a)?|d[äa]nisch\w*|deens",
    "no": r"norwegian|norv[ée]gien(?:ne)?|norvegese|noruego|norwegisch\w*|noors",
    "fi": r"finnish|finnois(?:e)?|finlandese|finland[ée]s(?:a)?|finnisch\w*",
    "cs": r"czech|tch[eè]que|ceco|checo|tschechisch\w*|tsjechisch",
    "sk": r"slovak|slovaque|slovacco|eslovaco|slowakisch\w*",
    "hu": r"hungarian|hongrois(?:e)?|ungherese|h[uú]ngaro|ungarisch\w*|hongaars",
    "ro": r"romanian|roumain(?:e)?|rumeno|rumano|rum[äa]nisch\w*|roemeens",
    "bg": r"bulgarian|bulgare|bulgaro|b[uú]lgaro|bulgarisch\w*",
    "hr": r"croatian|croate|croato|croata|kroatisch\w*",
    "sl": r"slovenian|slov[eè]ne|sloveno|slowenisch\w*",
    "lt": r"lithuanian|lituanien(?:ne)?|lituano|litauisch\w*",
    "lv": r"latvian|letton(?:e)?|lettone|let[oó]n|lettisch\w*",
    "et": r"estonian|estonien(?:ne)?|estone|estonio|estnisch\w*",
    "ru": r"russian|russe|russo|ruso|russisch\w*",
    "uk": r"ukrainian|ukrainien(?:ne)?|ucraino|ucraniano|ukrainisch\w*",
    "ar": r"arabic|arabe|arabo|[aá]rabe|arabisch\w*",
    "zh": r"chinese|mandarin|cantonese|chinois(?:e)?|cinese|chino|chinesisch\w*",
    "ja": r"japanese|japonais(?:e)?|giapponese|japon[eé]s(?:a)?|japanisch\w*",
    "ko": r"korean|cor[ée]en(?:ne)?|coreano|koreanisch\w*",
    "tr": r"turkish|turc|turque|turco|t[üu]rkisch\w*",
    "he": r"hebrew|h[ée]breu|ebraico|hebreo|hebr[äa]isch\w*",
    "it": r"italian|italien(?:ne)?|italiano|italienisch\w*|italiaans",
    "en": r"english|anglais(?:e)?|inglese|ingl[eé]s(?:a)?|englisch\w*|engels(?:e)?",
    "es": r"spanish|espagnol(?:e)?|spagnolo|espa[ñn]ol(?:a)?|castellano|spanisch\w*|spaans(?:e)?",
}
# "Polish" con la maiuscola (in minuscolo è il verbo "lucidare"): unico nome sensibile alle maiuscole
RE_NOMI = {k: re.compile(r"\b(?:" + v + r")\b", 0 if k == "pl" else re.I) for k, v in _NOMI_RE.items()}

RE_RICHIESTA = re.compile(
    r"(?i)\b(fluen\w*|native|mother[- ]tongue|proficien\w*|business[- ]level|working knowledge|"
    r"command of|written and (?:spoken|oral)|spoken and written|(?:is |are )?required|requirement|"
    r"mandatory|essential|must|speaking|speaker|bilingu\w*|[abc][12]\b|level|"
    r"courant|couramment|ma[iî]tris\w*|langue maternelle|parl[ée]e?s?|[ée]crit et oral|requis\w*|"
    r"exig\w*|indispensable|obligatoire|niveau|"
    r"madrelingua|fluente|ottim\w* conoscenza|buon\w* conoscenza|conoscenza|padronanza|"
    r"obbligatori\w*|richiest\w*|"
    r"flie(?:ß|ss)end\w*|verhandlungssicher\w*|sehr gut\w*|gut\w* \w*kenntnisse|\w*kenntnisse|"
    r"muttersprach\w*|zwingend|erforderlich|vorausgesetzt|"
    r"vloeiend\w*|uitstekend\w*|beheersing|vereist|"
    r"nivel|dominio|imprescindible|requerid\w*|nativo)\b")
RE_FACOLTATIVA = re.compile(
    r"(?i)\b(plus|asset|nice[- ]to[- ]have|advantage\w*|bonus|beneficial|desirable|preferr\w*|"
    r"preferabl\w*|would be|is a plus|optional|atout|avantage\w*|appr[ée]ci\w*|souhait\w*|"
    r"de pr[ée]f[ée]rence|gradit\w*|preferibil\w*|costituisce titolo|vorteil\w*|w[üu]nschenswert|"
    r"pluspunt|een pr[ée]|deseable|valorar\w*|se valora)\b")
RE_ALTERNATIVA = re.compile(r"(?i)(\b(?:or|ou|o|oppure|oder)\b|and/or|et/ou|e/o|\s/\s)")

# Parole frequenti per riconoscere la lingua del testo
_PAROLE = {
    "en": "the and to of in for with you our we will are is on your this be as an at have",
    "fr": "le les et des du pour vous nous est une dans avec sur au aux votre nos ce qui en",
    "it": "il di che per con del della un una sono nel alla dei delle gli siamo nostro nostra",
    "es": "el y que en los las para con del una por nuestro es tu su somos como al",
    "de": "der und das mit für wir sie ist zu den ein eine von auf bei ihre dich im uns sich nicht",
    "nl": "het van een voor met wij je zijn op te ons naar bij jij jouw wordt niet",
    "pt": "o os as em uma não nosso nossa com do da você para ao são",
}
_LISTE = {k: set(v.split()) for k, v in _PAROLE.items()}
RE_PAROLA = re.compile(r"[a-zà-öø-ÿß]+", re.I)

# Titoli tipicamente tedeschi (genere tra parentesi)
RE_TITOLO_TEDESCO = re.compile(r"(?i)\((?:m|w|d|f|x|div)\s*/\s*(?:m|w|d|f|x|div)(?:\s*/\s*(?:m|w|d|f|x|div))?\)"
                               r"|\b(werkstudent\w*|praktikant\w*|sachbearbeiter\w*|mitarbeiter\w*)\b")


# Titolo in francese (usato solo se manca la descrizione): almeno 2 indizi francesi
# e nessuna parola inglese tipica. "(H/F)" da solo non basta: si usa anche negli
# annunci in inglese pubblicati in Francia.
RE_INDIZI_FR = re.compile(
    r"(?i)\b(de|des|du|d'|en|et|pour|au|aux|le|la|les|ing[ée]nieur\w*|charg[ée]e?|chef|responsable|"
    r"stagiaire|stage|alternan\w*|apprenti\w*|technicien\w*|d[ée]veloppeur\w*|conseill[eè]re?|"
    r"gestionnaire|commerciale?|directeur|directrice|cdi|cdd|h/f|f/h)\b|[éèêàçùû]")
RE_INDIZI_EN = re.compile(
    r"(?i)\b(engineer\w*|manager|intern\w*|developer|officer|lead|head|senior|junior|analyst|"
    r"specialist|the|and|of|for|with)\b")


# Titolo chiaramente in spagnolo o italiano (lingue parlate): l'offerta resta anche se la
# descrizione sembra francese (es. PNO "Experto/a Técnico/a … Documentación de Proyectos",
# descrizione con testo di gruppo in francese).
RE_INDIZI_ES_IT = re.compile(
    r"(?i)\b(y|el|los|las|del|para|con|por|t[ée]cnic[oa](?:/a)?|expert[oa](?:/a)?|ingenier[oa]|"
    r"proyectos?|documentaci[óo]n|gesti[óo]n|desarrollador\w*|di|della|dello|degli|per|ingegnere|"
    r"tecnico|progett\w*|responsabile|addett[oa]|sviluppator\w*|tirocinio)\b|[áíóúñ]")


def titolo_parlato(titolo):
    return len(RE_INDIZI_ES_IT.findall(titolo or "")) >= 2


def titolo_francese(titolo):
    return len(RE_INDIZI_FR.findall(titolo or "")) >= 2 and not RE_INDIZI_EN.search(titolo or "")


def lingua_testo(testo):
    """Codice della lingua in cui è scritto il testo (it/en/fr/es/de/nl/pt) o ""
    se il testo è troppo corto o misto."""
    parole = [p.lower() for p in RE_PAROLA.findall(testo or "")]
    if len(parole) < 40:
        return ""
    conta = {k: sum(1 for p in parole if p in s) for k, s in _LISTE.items()}
    ordine = sorted(conta, key=conta.get, reverse=True)
    primo, secondo = ordine[0], ordine[1]
    if conta[primo] < 8 or conta[primo] < 1.5 * max(conta[secondo], 1):
        return ""
    return primo


def _frasi(testo):
    return [f for f in re.split(r"[\n\r•·;]+|(?<=[.!?])\s+", testo or "") if f.strip()]


FINESTRA = 60   # caratteri attorno al nome della lingua in cui cercare "fluent", "a plus"…


def lingue_richieste(testo):
    """Lingue chieste come requisito (non facoltative, non in alternativa a una parlata)."""
    richieste = set()
    for frase in _frasi(testo):
        for k, r in RE_NOMI.items():
            if k in PARLATE:
                continue
            for m in r.finditer(frase):
                vicino = frase[max(0, m.start() - FINESTRA): m.end() + FINESTRA]
                if not RE_RICHIESTA.search(vicino) or RE_FACOLTATIVA.search(vicino):
                    continue
                # "English or German": basta una lingua parlata
                if RE_ALTERNATIVA.search(vicino) and any(RE_NOMI[p].search(vicino) for p in PARLATE):
                    continue
                richieste.add(k)
                break
    return richieste


def valuta(titolo, testo):
    """(escludi, motivo, francese_richiesto)."""
    if RE_TITOLO_TEDESCO.search(titolo or ""):
        return True, "annuncio in tedesco", False
    scritta = lingua_testo(testo)
    if not (testo or "").strip() and titolo_francese(titolo):
        scritta = "fr"
    if scritta == "fr" and titolo_parlato(titolo):
        scritta = ""
    if scritta and scritta not in PARLATE:
        return True, f"annuncio in {NOMI[scritta]}", False
    richieste = lingue_richieste(f"{titolo}\n{testo or ''}")
    escluse = sorted(richieste - SEGNALATE)
    if escluse:
        return True, "richiesto " + ", ".join(NOMI[k] for k in escluse), False
    return False, "", "fr" in richieste
