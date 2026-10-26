# Aziende Target — Jobs Newsletter

Newsletter via email con le offerte di lavoro **solo delle aziende della lista
"Aziende Target Europa"** (progetto aziende-target-europa: dati CORDIS Horizon
Europe + aziende open innovation curate). Priorità **Parigi / Île-de-France**,
poi **Italia**, poi **da remoto**; le offerte in altre sedi si contano ma non si
mostrano. L'email parte solo quando ci sono offerte nuove.

Gira su GitHub Actions ogni mattina (`newsletter.yml`).

## Configurazione

Secret del repository (Settings → Secrets and variables → Actions):

- `GMAIL_MITTENTE`: indirizzo Gmail che invia
- `GMAIL_PASSWORD`: App Password di Gmail
- `EMAIL_DESTINATARIO`: uno o più indirizzi (separati da virgola), in CCN

## Primo avvio

1. Actions → "🔎 Cerca fonti" → Run workflow (cerca un portale di selezione per ogni azienda).
2. Actions → "🎯 Newsletter Aziende Target" → Run workflow.

Alla prima lettura di una fonte si mostrano solo le offerte degli ultimi 30 giorni;
quelle senza data diventano lo stato iniziale e da lì in poi si segnalano solo le nuove.

## File

| File | Cosa contiene |
|---|---|
| `dati/aziende.json` | La lista (1040 aziende). Si aggiorna con `python importa_aziende.py --html page.html` (pagina generata da `build_page.py` o salvata dall'artifact). |
| `dati/fonti_manuali.json` | Fonti scritte a mano: vincono su quelle automatiche. Lista vuota = nessuna fonte (es. stesso portale di un'altra voce dello stesso gruppo). |
| `dati/fonti.json` | Fonti trovate da `scopri_fonti.py` (ogni lunedì): portali e pagine carriere linkati dal sito ufficiale dell'azienda, o portali con lo stesso nome e annunci nei paesi dell'azienda. I casi dubbi finiscono in `da_verificare` e non si usano. |
| `dati/siti.json` | Sito ufficiale di ogni azienda, dai dati CORDIS (`python siti.py`). |
| `dati/seen.json` | Offerte già inviate (si dimenticano dopo 90 giorni senza vederle). |

## Fonti supportate

Lever, Greenhouse, Workable, SmartRecruiters, Ashby, Recruitee (API pubbliche),
Personio (XML), Workday (siti `myworkdayjobs.com`), Welcome to the Jungle
(pagina azienda) e una pagina "carriere" qualunque (`pagina`: segnala i link nuovi).

Per controllare cosa legge ogni fonte senza mandare email: Actions → "🧪 Prova fonti".

Esempio di fonte manuale:

```json
"euroquality": [{"tipo": "pagina", "url": "https://www.esempio.fr/carrieres", "nota": "verificata il ..."}]
```

## Test

```
python -m unittest -v test_newsletter
```
