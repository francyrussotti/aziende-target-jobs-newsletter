# Aziende Target — Jobs Newsletter

Newsletter email con le offerte di lavoro delle aziende della lista "Aziende
Target Europa" (progetto aziende-target-europa, pagina artifact
https://claude.ai/artifact/BqGmnoL15BCTRZwLmQvqfu). Utente: Fra, cerca lavoro a
Parigi (priorità massima), poi Italia. Lingua: italiano.

## Regole (dette dall'utente)

- **Solo aziende della lista** (`dati/aziende.json`): mai aggiungere aziende esterne.
  Una fonte va tenuta solo se è davvero dell'azienda (nome verificato o link dal sito ufficiale).
- Repository separato da BIG4-Jobs-Newsletter (non toccare quello).
- Lavoro fatto bene, niente scorciatoie: verificare sui run reali di GitHub Actions
  (da Claude Code la rete verso i portali è bloccata: usare il workflow "🧪 Prova fonti").
- Attenzione ai limiti di utilizzo: niente ricerche web superflue, pochi controlli dei run.
  Tenere aggiornato lo stato qui sotto, così una nuova sessione riparte senza perdere nulla.
- Non inventare dati: le fonti manuali hanno una `nota` con l'origine.
- Test sempre con **Python 3.11** (come GitHub Actions): `uv venv -p /usr/bin/python3.11 …` +
  requests/beautifulsoup4/lxml. Con il 3.13 locale è passato un errore (barra rovesciata in un'espressione
  f-string) che ha fatto fallire la run del 26/10 su GitHub.

## Come funziona

- `newsletter.py`: run giornaliera (workflow `newsletter.yml`), email ogni giorno (anche "nessuna offerta nuova"). `--prova [id…]` = solo lettura, nessuna email.
- `fonti.py`: lettori dei portali (lever, greenhouse, workable, smartrecruiters, ashby, recruitee,
  personio, workday, wttj, pagina) + classificazione sede (PAR/IT/REMOTO/FR/EU/ND/ALTRO) + scoperta per slug.
- `siti.py`: siti ufficiali dai dati CORDIS (`dati/siti.json`) e ricerca della pagina carriere / portale linkato.
- `scopri_fonti.py`: ricerca fonti (workflow `scopri-fonti.yml`, lunedì), max 40 minuti per run
  (in pratica ~11 minuti per 1040 aziende), salva a intervalli, riparte dalle aziende non ancora
  controllate (`controllate` in `dati/fonti.json`). `REGOLE` in scopri_fonti.py: se cambia, l'elenco
  riparte da zero; con le stesse regole le fonti confermate restano (un sito che non risponde una
  volta non fa sparire la fonte). Aziende in fonti_manuali.json escluse. Regole di accettazione:
  - portale linkato dal sito ufficiale (CORDIS) → accettato;
  - pagina carriere del sito → solo se contiene lessico da annunci (`siti.sembra_pagina_lavoro`),
    non è un articolo (>3 parole nell'ultimo pezzo dell'URL), non è una bacheca della rete/soci
    (`siti.bacheca_di_rete`) e l'indirizzo FINALE (dopo i redirect) è ancora una pagina carriere;
    mai "opportunities"/"talent"/"join us" da soli;
  - portale trovato per slug → nome con TUTTE le parole distintive + annunci in un paese
    dell'azienda (senza annunci → da_verificare, anche se il nome è identico);
  - nome solo compatibile (più corto) → `da_verificare` (non usato: controllare a mano e
    spostare in `fonti_manuali.json` se giusto).
- Lista aziende sempre allineata alla pagina: la routine claude.ai "Aziende target newsletter:
  importa lista" (ogni giorno 07:13 Roma, dopo l'aggiornamento della pagina delle 06:47) legge
  l'artifact, lancia `importa_aziende.py` (rifiuta se sparisce >20% della lista) e fa push di
  `dati/aziende.json` solo se cambia. Il push avvia `scopri-fonti.yml`: siti CORDIS aggiornati +
  `scopri_fonti.py --nuove` (solo aziende mai controllate). Le aziende uscite spariscono subito
  dalla newsletter (`carica_fonti` ignora gli ID fuori lista).
- Avvio giornaliero: i cron di newsletter.yml (4:37/6:37 UTC) partono dal 27/10 ma con 6-7 ore di
  ritardo (10:45-13:41 UTC). Avvio vero: routine claude.ai "Aziende target: lista + sveglia (sessione
  principale)" (trig_01WAZjZfJeBe18QMBVQ47gBc, 07:13 Roma) che arriva in QUESTA sessione
  (session_01W6X5HWY5pof66GCZnVaYRs, l'unica con permesso di push): importa la lista, scrive
  `dati/sveglia.txt`, push → newsletter.yml parte sul push. Doppio avvio innocuo (`ultima_run` ==
  oggi → stop). importa_aziende.py non riscrive il file se cambia solo la data.
  NB: la routine precedente (sessione nuova a ogni avvio) non poteva fare push (403, repo non tra le
  fonti) → 28-30/10 newsletter solo dai cron in ritardo. Una sessione figlia con il repo come fonte
  (session_01BhWxVLezMn2ihjzEVfMZKD) rifiuta i push chiesti da un'altra sessione: non usarla.
- Filtro lingua (`lingue.py`, chiesto dall'utente 26/10): Fra parla italiano, inglese, spagnolo,
  francese di base. Esclusa un'offerta scritta in un'altra lingua (es. tedesco, titoli "(m/w/d)")
  o che CHIEDE una lingua non parlata (fluent/native/courant/fließend… entro 60 caratteri dal nome
  della lingua), salvo se facoltativa ("a plus", "un atout", "titolo preferenziale") o in alternativa
  a una parlata ("English or German"). Annunci TUTTI IN FRANCESE esclusi (chiesto dall'utente 26/10;
  senza descrizione si guarda il titolo: `titolo_francese`, "(H/F)" da solo non basta); un annuncio
  in inglese che chiede anche francese fluente resta con la chip «francese fluente».
  Senza descrizione leggibile l'offerta resta. Descrizioni: già nell'elenco per lever/greenhouse
  (content=true)/workable (details=true)/ashby/recruitee/personio XML; per Workday e SmartRecruiters
  dall'API di dettaglio, per le pagine dalla pagina dell'annuncio, solo per le offerte da mostrare
  (max MAX_DETTAGLI=1200 per run). Le escluse restano in seen.json (non tornano). Verifica:
  prova-fonti con opzione "lingua" (max 30 offerte per fonte).
- `dati/fonti_manuali.json` vince su `dati/fonti.json`; `dati/siti_manuali.json` corregge i siti
  CORDIS vecchi (vince su `dati/siti.json`). Workflow ricerca: input "aziende" per rifarla su pochi ID.
- Prima lettura di una fonte: portale strutturato → tutte le offerte aperte in focus ("già aperta");
  pagina generica → stato iniziale silenzioso. Poi solo le nuove.

## Stato e cose da fare

- [x] Repo creato, secret Gmail aggiunti dall'utente, test verdi su GitHub.
- [x] Fonti manuali verificate su GitHub (prova 26/10): PNO 14, Novaspace 25, Starburst 5,
      Hello Tomorrow 1, Commpla 1, LGI 0 (WTTJ, nessuna offerta aperta).
- [x] Workday: Thales 2000 offerte lette (686 Parigi/IDF, 25 Italia) con il filtro per paese;
      ora un paese alla volta (limite 2000 di Workday) — da riverificare con la prova.
- [x] 1ª ricerca (slug) scartata: omonimi (Alliance, Space, Advanced, Hive, Amplitude…).
- [x] 2ª ricerca (run 40347272318, 208 aziende con fonte) scartata dopo revisione a mano:
      pagine di adesione/articoli/bandi prese per "carriere", nomi "identici" falsi
      (Trust-It→Trust, Hydrogen Europe Research→Hydrogen, A.Spire→Spire), Thales Workday doppio.
      Copia per confronto: nessuna nel repo (era nel commit 6138b41).
- [x] Revisione completa del codice (26/10): corretti email oltre il limite Gmail (~102 KB),
      doppioni tra portali, link "vedi tutte" per ogni portale, "Remote Sensing" ≠ remoto,
      sede solo "France" mostrata a parte, link con parametri volatili, WTTJ 403 → browser,
      sedi non indicate solo per aziende Parigi/Italia, email del lunedì se ci sono fonti rotte,
      workflow newsletter non lancia più la ricerca (sforava il timeout). 42 test.
- [x] 3ª ricerca (run su 19b620a): 107 aziende con fonte, 3 da verificare. Riletta tutta: errori
      residui corretti (Actia → home dopo redirect; Axelera/Polymeris bacheche dei soci;
      ENTSO-E → www.teamtailor.com; Euronovia → articolo). 45 test.
- [x] 4ª ricerca (su e3f8c52): 101 aziende con fonte. Riletta tutta: unico errore Euronovia
      (WordPress rimanda /recrutement a un articolo → ora controllo articoli anche sull'URL finale).
- [x] Dubbi decisi a mano con prova-fonti (dubbi): Avantium → confermato (fonti_manuali);
      Magellan → è Magellan Partners (consulenza IT Parigi), scartato; Saint-Gobain → annunci
      solo del 2018, portale abbandonato, scartato. Decisioni in fonti_manuali.json (`_scartate`).
- [x] Prima lettura: "già aperte" solo se pubblicate negli ultimi 365 giorni (portali abbandonati).
- [x] Nome identico senza annunci (Agorize, Bpifrance, GAC, Innova su Workable) → da_verificare.
- [x] 5ª ricerca (su a5f19ab): 98 aziende con fonte; uscite attese (Euronovia, 4 workable →
      da verificare). Trovata instabilità: Robotnik uscita, Civitta/Ubimet rientrate (siti lenti)
      → ora unione delle fonti con le stesse REGOLE (=5). Dubbi già decisi a mano tolti dagli elenchi.
- [x] Prova di TUTTE le fonti (run 40359050288, log letto per intero): 105 aziende, 108 fonti,
      102 funzionanti, 3090 offerte (PAR 755, IT 68, remoto 19, ND 376, altre 1872).
      Thales 699 PAR + 63 IT (lettura per paese ok), Valeo 21, UTAC 12+4, Novaspace 10, PNO 3+1.
      Errori trovati e corretti: le 376 "ND" erano quasi tutte link spazzatura delle pagine carriere
      dei grandi gruppi (Nokia "Life at Nokia", Siemens "Explore all jobs", Sanofi…) → ora dalle
      pagine si tengono solo link con un titolo di lavoro (`fonti.RE_TITOLO_LAVORO`); Repsol Workday
      con lingua breve "/es" (404); Naturland Personio senza XML → lettura pagina pubblica. 50 test.
- [x] Ricerca REGOLE=6 + statistiche (run 40361319424): 98 aziende con fonte; Repsol ora
      workday …/es/Repsol; Robotnik rientrata (home con tentativi). Siti ufficiali: 390, provati 382,
      raggiunti 288 (75%), con pagina carriere/portale 96, irraggiungibili 94 (domini CORDIS vecchi).
      Dubbi: 7 workable "nome identico senza annunci" (Bpifrance, Engie, GAC, Innova, Agorize, Polis, Surf).
- [x] siti_manuali.json: RINA (2 voci) → rina.org, Engie → engie.com, Erdyn → erdyn.com.
      Irraggiungibili prioritari senza correzione: INRAE Transfert (inra-transfert.fr), Tinexta
      Innovation Hub (warrantgroup.eu) → da segnalare all'utente.
- [x] Ricerca mirata su RINA/Engie/Erdyn con siti corretti: siti raggiunti, nessuna pagina
      carriere leggibile (grandi gruppi con portali propri) → senza fonte.
- [x] 2ª prova di TUTTE le fonti (run 40366859472, letta per intero, 357 righe): 105/109 funzionanti,
      0 errori, 2878 offerte (PAR 755, IT 68, remoto 19, ND 96 invece di 376). Falle corrette:
      comuni IDF mancanti (CS Group a Le Plessis-Robinson finiva in "altre sedi") → elenco comuni +
      codici postali; link non-annuncio residui ("Operations", privacy, "Meet …", programmi,
      ricerche ?search=) → RE_NON_ANNUNCIO; candidature spontanee/"Join…" escluse da ogni fonte;
      sede ricavata dal titolo se manca ("… Rome Italy"); titoli ripetuti/"More Details" puliti. 56 test.
- [x] Modalità diagnosi (scopri_fonti.py --diagnosi, workflow opzione "diagnosi"): lanciata sulle
      42 aziende prioritarie senza fonte (run su c15474f) → leggere e aggiungere fonti manuali.
- [x] 3ª prova di TUTTE le fonti (run 40368146801): 105/109, 0 errori, 2848 offerte; PAR 939
      (era 755: Thales 832, Valeo 49, CS Group 13, UTAC 22 grazie ai comuni IDF), IT 70, ND 76 puliti.
- [x] Diagnosi 42 prioritarie (run 40367058375, letta per intero): WTTJ risponde HTTP 202 (anti-bot)
      a ogni richiesta diretta → la ricerca su WTTJ non funzionava mai. RINA/Engineering: pagina
      carriere in JavaScript; Engie: scelta la home come pagina carriere (bug); Bpifrance: CORDIS
      ha oseo.fr; Euronovia: annunci come articoli; Meta Group: pagine carriere → home;
      19 senza sito in CORDIS. Corretto: WTTJ nella ricerca con il browser (solo FR del focus
      Parigi), home mai pagina carriere, siti_manuali Bpifrance → bpifrance.fr. REGOLE=7. 59 test.
- [x] 1ª newsletter (run 40369302568) FALLITA all'invio: raccolta ok (2847 offerte, 955 da mostrare,
      email 75 KB) ma Gmail chiude la connessione ("Connection unexpectedly closed", 3 volte).
      Corretto: secret ripuliti da spazi/"a capo", porta 587 STARTTLS di riserva, log della fase e
      della lunghezza password (16 attesi). Newsletter in un gruppo di concorrenza proprio. 61 test.
- [x] Newsletter rilanciata 3 volte (run 40370035884, 40370636065 = errore sintassi 3.11 mio,
      40372291915): raccolta ok (955 offerte, 75 KB), login Gmail sempre "Connection unexpectedly
      closed" su 465 e 587. Controlli secret: mittente Gmail ASCII senza spazi, password 16 lettere
      minuscole → formato giusto ma valore non valido (Big4 invia con le sue credenziali).
- [x] Nuova App Password messa dall'utente → 1ª newsletter INVIATA (run 40381057806, 26/10):
      2851 offerte, 965 mostrate, email 81 KB, porta 465; seen.json creato (1042 offerte, commit 4ec5d01).
      Dalle prossime run solo le offerte nuove.
- [x] Ricerca REGOLE=7 con browser per WTTJ (run 40369605324): 97 aziende con fonte; WTTJ trova
      Artelys (nuova) e CS Group; prioritarie con fonte ancora 8/54.
- [x] EMAIL_DESTINATARIO era sbagliato (mail non arrivata a francy.russotti@gmail.com): corretto
      dall'utente, seen.json azzerato (cb310ba) e newsletter reinviata.
- [x] Aggiornamento automatico della lista aziende (routine + push → ricerca solo nuove). 63 test.
- [x] Filtro lingua verificato (prova-fonti run 40386672034, log letto per intero, 708 righe): nessun
      falso positivo; escluse giuste 7 GSI (annunci in tedesco) e 7 IDIADA (Brasile, portoghese);
      descrizioni lette per Thales/Valeo (Workday), UTAC/IDIADA (SmartRecruiters), Lever, Personio
      PNO, pagine. Senza descrizione (tenute): WTTJ (CS Group 13, Artelys 9: serve il browser, non
      usato per le descrizioni), Personio Technopolis 5, Liber 10/18. Trovato: IDIADA aveva 12
      "remoto" in Brasile → ora remoto solo se Europa o paese non indicato (PAESI_EUROPA,
      RE_FUORI_EUROPA). 70 test.
- [x] Esclusione annunci in francese verificata (prova-fonti run 40391156251, log letto per intero,
      735 righe; campione max 30 per fonte): Thales 29/30 esclusi, Valeo 23/30, UTAC 21/26, CS Group
      12/13, Amplitude 15/15, Artelys 5/9; Novaspace 0/11 (in inglese). Unico errore: PNO "Experto/a
      Técnico/a … Documentación de Proyectos" (spagnolo) preso per francese → titolo chiaramente
      spagnolo/italiano (`titolo_parlato`) vince sulla descrizione. Effetto: Parigi da ~940 offerte
      a qualche decina. 73 test.
- [x] 27/10: routine importa lista OK (invariata, nessun commit); newsletter NON partita (cron
      GitHub mai scattati) → lanciata a mano + riserva sveglia.txt via routine. 74 test.
- [x] Newsletter 27/10 (run 40482357879): 2849 offerte lette, 14 nuove in focus, tutte Thales in
      francese → escluse; nessuna email (nessuna novità). Run da sveglia.txt (40482443687) fermata
      subito ("già fatta"): riserva funzionante.
- [x] Email ogni giorno anche senza offerte nuove (chiesto dall'utente 27/10): oggetto "nessuna
      offerta nuova (N escluse per lingua, M fonti da controllare)"; non inviata solo se la rete è
      caduta (>metà fonti in errore → run fallita). 75 test.
- [x] Sezione "Altre sedi in Europa" (EU, chiesto dall'utente 28/10): tf.luogo → EU se paese europeo
      (PAESI_EUROPA) o città/paese in RE_EUROPA (Toulouse, Lyon, Munich, Brussels…); fuori Europa
      (RE_FUORI_EUROPA o paese extra-UE) → ALTRO, nascosto. Scelta utente: solo le offerte NUOVE, mai
      le già aperte: al primo giro dopo l'introduzione (seen["zone"] senza "EU") e alla prima lettura
      di una fonte le EU si segnano come viste in silenzio. Filtro lingua attivo anche qui. 78 test.
- [x] 30/10: "fail" = notifiche della routine (push 403 dal 28/10). Newsletter 28-29/10 arrivate tardi
      (cron in ritardo), 30/10 avviata a mano (ef2ce93, 11 nuove). Routine spostata in questa sessione.
- [ ] Aziende prioritarie (Parigi/Italia, classe A o open innovation) ancora senza fonte:
      elencarle per l'utente.
