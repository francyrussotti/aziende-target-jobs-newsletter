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

## Come funziona

- `newsletter.py`: run giornaliera (workflow `newsletter.yml`). `--prova [id…]` = solo lettura, nessuna email.
- `fonti.py`: lettori dei portali (lever, greenhouse, workable, smartrecruiters, ashby, recruitee,
  personio, workday, wttj, pagina) + classificazione sede (PAR/IT/REMOTO/ND/ALTRO) + scoperta per slug.
- `siti.py`: siti ufficiali dai dati CORDIS (`dati/siti.json`) e ricerca della pagina carriere / portale linkato.
- `scopri_fonti.py`: ricerca fonti (workflow `scopri-fonti.yml`, lunedì), max 40 minuti per run
  (in pratica ~11 minuti per 1040 aziende), salva a intervalli, riparte dalle aziende non ancora
  controllate (`controllate5` in `dati/fonti.json`). A ogni controllo le fonti di un'azienda si
  sostituiscono. Regole di accettazione:
  - portale linkato dal sito ufficiale (CORDIS) → accettato;
  - pagina carriere del sito → solo se contiene lessico da annunci (`siti.sembra_pagina_lavoro`),
    non è un articolo (>3 parole nell'ultimo pezzo dell'URL), non è una bacheca della rete/soci
    (`siti.bacheca_di_rete`) e l'indirizzo FINALE (dopo i redirect) è ancora una pagina carriere;
    mai "opportunities"/"talent"/"join us" da soli;
  - portale trovato per slug → nome con TUTTE le parole distintive + annunci in un paese
    dell'azienda (senza annunci → da_verificare, anche se il nome è identico);
  - nome solo compatibile (più corto) → `da_verificare` (non usato: controllare a mano e
    spostare in `fonti_manuali.json` se giusto).
- `dati/fonti_manuali.json` vince su `dati/fonti.json`.
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
- [ ] 5ª ricerca (controllate5) con queste ultime regole; rileggere l'elenco.
- [ ] Prova fonti su tutte le fonti trovate; correggere quelle rotte o sbagliate.
- [ ] Prima newsletter reale (workflow "🎯 Newsletter Aziende Target") e controllo dell'email
      (dimensione, sezioni, link).
- [ ] Aziende prioritarie (Parigi/Italia, classe A o open innovation) ancora senza fonte:
      elencarle per l'utente.
