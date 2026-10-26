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
- `scopri_fonti.py`: ricerca fonti (workflow `scopri-fonti.yml`, lunedì), max 40 minuti per run,
  salva a intervalli, riparte dalle aziende non ancora controllate (`controllate2` in `dati/fonti.json`).
- `dati/fonti_manuali.json` vince su `dati/fonti.json`.
- Prima lettura di una fonte: portale strutturato → tutte le offerte aperte in focus ("già aperta");
  pagina generica → stato iniziale silenzioso. Poi solo le nuove.

## Stato e cose da fare

- [x] Repo creato, secret Gmail aggiunti dall'utente, test verdi su GitHub.
- [x] Fonti manuali verificate su GitHub (prova 26/10): PNO 14, Novaspace 25, Thales, Starburst 6,
      Hello Tomorrow 1, Commpla 1, LGI 0 (WTTJ, nessuna offerta aperta).
- [ ] Verificare su GitHub il fix Workday per paese (Thales: attese molte più offerte in Île-de-France).
- [ ] Scoperta fonti completa su tutte le 1040 aziende (siti ufficiali CORDIS + slug); controllare
      nel log i falsi positivi, soprattutto sulle aziende prioritarie (Parigi / Italia).
- [ ] Prova fonti su tutte le fonti trovate; correggere quelle rotte o sbagliate.
- [ ] Prima newsletter reale (workflow "🎯 Newsletter Aziende Target") e controllo dell'email.
- [ ] Aziende prioritarie (Parigi/Italia, classe A o open innovation) ancora senza fonte:
      elencarle per l'utente.
