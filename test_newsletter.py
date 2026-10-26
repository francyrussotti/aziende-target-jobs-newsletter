"""Test offline della newsletter: nessuna rete, nessuna email.
Avvio:  python -m unittest -v test_newsletter
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import fonti as tf
import newsletter as tn


def giorni_fa(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


class FintaRisposta:
    def __init__(self, dati=None, testo="", contenuto=b"", status=200):
        self._dati, self.text, self.content, self.status_code = dati, testo, contenuto, status

    def json(self):
        if self._dati is None:
            raise ValueError
        return self._dati


class TestNomi(unittest.TestCase):
    def test_slug_senza_forme_societarie(self):
        self.assertEqual(tf.slug_candidati("Euroquality SAS")[0], "euroquality")
        c = tf.slug_candidati("Lgi Sustainable Innovation")
        self.assertIn("lgisustainableinnovation", c)
        self.assertIn("lgi-sustainable-innovation", c)
        self.assertNotIn("lgi", c)                       # troppo corto da solo

    def test_nome_corrisponde(self):
        self.assertTrue(tf.nome_corrisponde("Rina Consulting SPA", "RINA"))
        self.assertTrue(tf.nome_corrisponde("Engie", "ENGIE Italia"))
        self.assertTrue(tf.nome_corrisponde("Hello Tomorrow", "Hello Tomorrow"))
        self.assertTrue(tf.nome_corrisponde("Csc-Tieteen Tietotekniikan Keskus OY", "CSC Tieteen Tietotekniikan Keskus"))
        self.assertFalse(tf.nome_corrisponde("Innova SRL", "Innovaphone"))
        self.assertFalse(tf.nome_corrisponde("Gac", "Gucci"))
        self.assertFalse(tf.nome_corrisponde("Erdyn Consultants SAS", "Capgemini Consulting"))
        # Falsi positivi visti nella prima ricerca (26/10/2026)
        self.assertFalse(tf.nome_corrisponde("Space Applications Services NV", "Space Programs"))
        self.assertFalse(tf.nome_corrisponde("Advanced Computing Spain SL", "Advanced Schema"))
        self.assertFalse(tf.nome_corrisponde("Iris Technology Solutions", "Iris North America"))
        self.assertFalse(tf.nome_corrisponde("Impact Hub GMBH", "impact.com"))
        self.assertFalse(tf.nome_uguale("Alliance For New Mobility Europe", "Alliance"))
        self.assertTrue(tf.nome_uguale("Agorize", "Agorize"))

    def test_annunci_nei_paesi(self):
        self.assertTrue(tf.annunci_nei_paesi([{"location": "Paris, France"}], ["FR"]))
        self.assertTrue(tf.annunci_nei_paesi([{"location": "", "paese": "GB"}], ["UK"]))
        self.assertTrue(tf.annunci_nei_paesi([{"location": "Athens"}], ["EL"]))
        self.assertFalse(tf.annunci_nei_paesi([{"location": "San Francisco, CA", "paese": "US"}], ["FR"]))
        self.assertFalse(tf.annunci_nei_paesi([], ["FR"]))

    def test_prova_scarta_omonimi_di_altri_paesi(self):
        az = {"n": "Hive Power SA", "p": "CH"}
        usa = [tf._offerta("Engineer", "https://x/1", "New York, NY", "US")]
        with mock.patch.object(tf, "_json", return_value={"name": "Hive"}), \
             mock.patch.object(tf, "leggi_fonte", return_value=usa):
            self.assertIsNone(tf._prova("greenhouse", "hive", az))
        svizzera = [tf._offerta("Engineer", "https://x/1", "Lugano")]
        with mock.patch.object(tf, "_json", return_value={"name": "Hive Power"}), \
             mock.patch.object(tf, "leggi_fonte", return_value=svizzera):
            self.assertEqual(tf._prova("greenhouse", "hivepower", az)["tipo"], "greenhouse")
        # Nome identico ma nessun annuncio: non verificabile → da verificare, non usato
        with mock.patch.object(tf, "_json", return_value={"name": "Agorize"}), \
             mock.patch.object(tf, "leggi_fonte", return_value=[]):
            self.assertIn("da_verificare", tf._prova("workable", "agorize", {"n": "Agorize", "p": "FR"}))

    def test_testo_cita_nome(self):
        self.assertTrue(tf.testo_cita_nome("Novaspace GMBH", ["At Novaspace, we advise…"]))
        self.assertFalse(tf.testo_cita_nome("Novaspace GMBH", ["We are a space company"]))


class TestLuogo(unittest.TestCase):
    def caso(self, loc, paese="", remoto=False, titolo=""):
        return tf.luogo({"location": loc, "paese": paese, "remoto": remoto, "titolo": titolo})

    def test_sezioni(self):
        self.assertEqual(self.caso("Paris, France"), "PAR")
        self.assertEqual(self.caso("La Défense"), "PAR")
        self.assertEqual(self.caso("Boulogne-Billancourt"), "PAR")
        self.assertEqual(self.caso("Milano, Lombardia"), "IT")
        self.assertEqual(self.caso("Rome"), "IT")
        self.assertEqual(self.caso("", paese="IT"), "IT")
        self.assertEqual(self.caso("Toulouse, France"), "ALTRO")
        self.assertEqual(self.caso("Madrid", remoto=True), "REMOTO")
        self.assertEqual(self.caso("Europe - Remote"), "REMOTO")
        self.assertEqual(self.caso(""), "ND")
        self.assertEqual(self.caso("Munich / Paris"), "PAR")   # Parigi vince


class TestLettori(unittest.TestCase):
    def test_lever(self):
        dati = [{"text": "Junior Consultant", "hostedUrl": "https://jobs.lever.co/x/1",
                 "createdAt": 1790000000000, "workplaceType": "hybrid", "country": "FR",
                 "categories": {"location": "Paris", "allLocations": ["Paris", "Toulouse"]}}]
        with mock.patch.object(tf, "_json", return_value=dati) as j:
            o = tf.lever("novaspace")
        self.assertIn("api.lever.co/v0/postings/novaspace", j.call_args[0][0])
        self.assertEqual(o[0]["location"], "Paris / Toulouse")
        self.assertEqual(o[0]["paese"], "FR")
        self.assertRegex(o[0]["data"], r"^\d{4}-\d{2}-\d{2}$")

    def test_smartrecruiters_pagina(self):
        pag = lambda n, tot: {"totalFound": tot, "content": [
            {"id": f"{n}-{i}", "name": "Analyst", "releasedDate": "2026-10-20T10:00:00Z",
             "location": {"city": "Milano", "country": "it"}} for i in range(n)]}
        with mock.patch.object(tf, "_json", side_effect=[pag(100, 130), pag(30, 130)]) as j:
            o = tf.smartrecruiters("Acme")
        self.assertEqual(len(o), 130)
        self.assertEqual(j.call_count, 2)
        self.assertEqual(o[0]["paese"], "IT")
        self.assertTrue(o[0]["url"].startswith("https://jobs.smartrecruiters.com/Acme/"))

    def test_personio(self):
        xml = b"""<workzag-jobs><position><id>42</id><office>Paris</office>
        <additionalOffices><office>Milan</office></additionalOffices>
        <name>Innovation Consultant</name><createdAt>2026-10-01T09:00:00+00:00</createdAt>
        </position></workzag-jobs>"""
        with mock.patch.object(tf, "_get", return_value=FintaRisposta(contenuto=xml)):
            o = tf.personio("pno-group-europe", dominio="jobs.personio.com")
        self.assertEqual(o[0]["url"], "https://pno-group-europe.jobs.personio.com/job/42")
        self.assertEqual(o[0]["location"], "Paris / Milan")
        self.assertEqual(o[0]["data"], "2026-10-01")

    def test_workday_un_paese_alla_volta(self):
        facets = [{"facetParameter": "locationCountry", "values": [
            {"id": "fr1", "descriptor": "France"}, {"id": "de1", "descriptor": "Germany"},
            {"id": "it1", "descriptor": "Italy"}]}]
        righe = lambda pref, n, da=0: [{"title": f"{pref} {i}", "externalPath": f"/job/{pref}{i}",
                                        "locationsText": "Paris", "postedOn": "Posted 2 Days Ago"}
                                       for i in range(da, da + n)]
        chiamate = []

        def finto(url, **kw):
            corpo = kw["json"]
            chiamate.append((corpo["appliedFacets"], corpo["offset"]))
            filtro = corpo["appliedFacets"].get("locationCountry", [None])[0]
            if filtro is None:
                return {"total": 9999, "facets": facets, "jobPostings": righe("x", 20)}
            if filtro == "fr1":
                return {"total": 25, "jobPostings": righe("fr", 20)} if corpo["offset"] == 0 \
                    else {"jobPostings": righe("fr", 5, 20)}
            return {"total": 3, "jobPostings": righe("it", 3)}

        with mock.patch.object(tf, "_json", side_effect=finto):
            o = tf.workday("https://thales.wd3.myworkdayjobs.com/fr-FR/Careers")
        self.assertEqual(len(o), 28)                      # 25 Francia + 3 Italia
        self.assertNotIn({"locationCountry": ["de1"]}, [c[0] for c in chiamate])
        self.assertEqual(o[0]["url"], "https://thales.wd3.myworkdayjobs.com/fr-FR/Careers/job/fr0")
        self.assertEqual(o[0]["data"], giorni_fa(2))

    def test_workday_preferisce_il_paese_alle_sedi(self):
        facets = [{"facetParameter": "locations", "values": [
                      {"id": "p9", "descriptor": "PARIS 9ème"}, {"id": "vz", "descriptor": "Vélizy"}]},
                  {"facetParameter": "Location_Country", "values": [
                      {"id": "fr", "descriptor": "France"}, {"id": "it", "descriptor": "Italy"}]}]
        self.assertEqual(tf._workday_facet(facets), {"Location_Country": ["fr", "it"]})
        self.assertEqual(tf._workday_facet([{"facetParameter": "locations", "values": [
            {"id": "p9", "descriptor": "PARIS 9ème"}]}]), {})

    def test_wttj(self):
        html = """<a href="/fr/companies/hello-tomorrow/jobs/deep-tech-intern_paris_HT_V1">Deep Tech Intern</a>
                  <a href="/fr/companies/hello-tomorrow/jobs/deep-tech-intern_paris_HT_V1">doppione</a>
                  <a href="/fr/companies/hello-tomorrow/jobs/spontaneous-application_paris">Spontanea</a>
                  <a href="/fr/companies/hello-tomorrow/jobs/rejoins-nous_paris">Candidature spontanée chez nous</a>
                  <a href="/fr/companies/altra/jobs/x_paris">Altra azienda</a>"""
        o = tf._wttj_estrai("hello-tomorrow", html)
        self.assertEqual(len(o), 1)
        self.assertEqual(o[0]["titolo"], "Deep Tech Intern")
        self.assertEqual(o[0]["location"], "Paris")

    def test_pagina_generica(self):
        html = """<nav><a href="/careers/menu-voice-long">Voce di menu lunga</a></nav>
          <a href="/careers">Careers</a>
          <a href="/careers/junior-project-manager">Junior Project Manager (EU projects)</a>
          <a href="https://jobs.lever.co/acme/123">Communication Officer - Pisa</a>
          <a href="https://facebook.com/careers/x">Seguici su Facebook ora</a>
          <a href="/news/una-notizia-qualunque">Una notizia qualunque</a>"""
        o = tf.estrai_link_annunci(html, "https://acme.com/careers")
        self.assertEqual([x["titolo"] for x in o],
                         ["Junior Project Manager (EU projects)", "Communication Officer - Pisa"])


class ConCartella(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        p = lambda n: os.path.join(self.dir.name, n)
        for attr, nome in [("AZIENDE_FILE", "aziende.json"), ("FONTI_FILE", "fonti.json"),
                           ("FONTI_MANUALI_FILE", "fonti_manuali.json"), ("SEEN_FILE", "seen.json")]:
            patcher = mock.patch.object(tn, attr, p(nome))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.aziende = [
            {"id": "acme-par", "n": "Acme Paris", "p": "FR", "k": "PAR", "c": "A", "l": 1, "s": 90, "o": 0},
            {"id": "acme-it", "n": "Acme Italia", "p": "IT", "k": "IT", "c": "A", "l": 1, "s": 80, "o": 0},
        ]
        self.scrivi("aziende.json", {"generato": "26/10/2026", "aziende": self.aziende})

    def scrivi(self, nome, dati):
        with open(os.path.join(self.dir.name, nome), "w") as f:
            json.dump(dati, f)


class TestFonti(ConCartella):
    def test_solo_aziende_in_lista_e_manuali_vincono(self):
        self.scrivi("fonti.json", {"fonti": {
            "acme-par": [{"tipo": "lever", "slug": "auto"}],
            "fuori-lista": [{"tipo": "lever", "slug": "x"}]}})
        self.scrivi("fonti_manuali.json", {"_nota": "x", "acme-par": [{"tipo": "lever", "slug": "manuale"}],
                                           "acme-it": []})
        f = tn.carica_fonti(tn.carica_aziende())
        self.assertEqual(f, {"acme-par": [{"tipo": "lever", "slug": "manuale"}]})

    def test_portale_condiviso_letto_una_volta(self):
        az = tn.carica_aziende()
        stessa = {"tipo": "personio", "slug": "gruppo"}
        with mock.patch.object(tf, "leggi_fonte", return_value=[]) as lf:
            r = tn.raccogli(az, {"acme-it": [stessa], "acme-par": [dict(stessa)]})
        self.assertEqual(lf.call_count, 1)
        self.assertEqual(r[0][0], "acme-par")              # va all'azienda con priorità più alta


class TestSelezione(ConCartella):
    def offerta(self, titolo, loc="Paris", data=""):
        return {"titolo": titolo, "location": loc, "paese": "", "remoto": False,
                "url": f"https://x/{titolo}", "data": data}

    def test_prima_lettura_e_successive(self):
        az = tn.carica_aziende()
        fonte = {"tipo": "lever", "slug": "acme"}
        seen = {"ids": {}, "fonti": [], "storico": []}
        offerte = [self.offerta("recente", data=giorni_fa(3)), self.offerta("vecchia", data=giorni_fa(60)),
                   self.offerta("senza-data"), self.offerta("madrid", loc="Madrid", data=giorni_fa(1)),
                   self.offerta("del-2018", data="2018-09-10")]      # portale abbandonato
        nuove, stat = tn.seleziona(az, [("acme-par", fonte, offerte, None)], seen, giorni_fa(0))
        # Prima lettura di un portale: tutte le aperte in focus, segnate "già aperta"
        self.assertEqual([o["titolo"] for o in nuove], ["recente", "vecchia", "senza-data"])
        self.assertTrue(all(o["gia_aperta"] for o in nuove))
        self.assertEqual((stat["fuori_focus"], stat["vecchie"]), (1, 1))
        # Run successiva: le note non tornano; una nuova sì, una nuova ma vecchia no
        nuove, stat = tn.seleziona(az, [("acme-par", fonte, offerte + [
            self.offerta("nuova"), self.offerta("ripubblicata", data=giorni_fa(90))], None)], seen, giorni_fa(0))
        self.assertEqual([o["titolo"] for o in nuove], ["nuova"])
        self.assertNotIn("gia_aperta", nuove[0])
        self.assertEqual(stat["vecchie"], 1)          # la ripubblicata (la 2018 è già nello storico)

    def test_pagina_generica_prima_lettura_silenziosa(self):
        az = tn.carica_aziende()
        fonte = {"tipo": "pagina", "url": "https://acme.fr/careers"}
        seen = {"ids": {}, "fonti": [], "storico": []}
        nuove, stat = tn.seleziona(az, [("acme-par", fonte, [self.offerta("link", loc="")], None)],
                                   seen, giorni_fa(0))
        self.assertEqual((nuove, stat["iniziali"]), ([], 1))
        nuove, _ = tn.seleziona(az, [("acme-par", fonte, [self.offerta("link", loc=""),
                                                         self.offerta("annuncio", loc="")], None)],
                                seen, giorni_fa(0))
        self.assertEqual([o["titolo"] for o in nuove], ["annuncio"])

    def test_oblio(self):
        seen = {"ids": {"vecchio": giorni_fa(200), "recente": giorni_fa(5)}, "fonti": [], "storico": []}
        tn.seleziona({}, [], seen, giorni_fa(0))
        self.assertEqual(list(seen["ids"]), ["recente"])

    def test_controlli(self):
        f = {"tipo": "lever", "slug": "acme"}
        storico = [{"conteggi": {"lever:acme": 4}}]
        self.assertEqual(len(tn.controlli([("acme-par", f, [], None)], storico)), 1)
        self.assertEqual(len(tn.controlli([("acme-par", f, None, "timeout")], [])), 1)
        self.assertEqual(tn.controlli([("acme-par", f, [], None)], []), [])


class TestMain(ConCartella):
    def setUp(self):
        super().setUp()
        self.scrivi("fonti_manuali.json", {"acme-par": [{"tipo": "lever", "slug": "acme"}]})
        self.offerte = [{"titolo": "Stagiaire innovation", "location": "Paris", "paese": "FR",
                         "remoto": False, "url": "https://x/1", "data": giorni_fa(1)}]

    def lancia(self, stato_invio):
        with mock.patch.object(tf, "leggi_fonte", return_value=self.offerte), \
             mock.patch.object(tn, "invia_email", return_value=stato_invio) as invio, \
             mock.patch.dict(os.environ, {"NEWSLETTER_FORZA": ""}):
            try:
                tn.main()
                codice = 0
            except SystemExit as e:
                codice = e.code
        return invio, codice

    def test_invio_ok_salva_storico(self):
        invio, codice = self.lancia("ok")
        self.assertEqual(codice, 0)
        html = invio.call_args[0][0]
        self.assertIn("Stagiaire innovation", html)
        self.assertIn("Acme Paris", html)
        self.assertIn("Parigi 1", invio.call_args[0][1])
        self.assertEqual(len(tn.carica_seen()["ids"]), 1)
        # Seconda run lo stesso giorno: si ferma subito
        invio2, _ = self.lancia("ok")
        invio2.assert_not_called()

    def test_invio_fallito_non_salva(self):
        _, codice = self.lancia("auth")
        self.assertEqual(codice, 1)
        self.assertFalse(os.path.exists(tn.SEEN_FILE))

    def test_seen_corrotto_blocca(self):
        with open(tn.SEEN_FILE, "w") as f:
            f.write('{"ids": {')
        _, codice = self.lancia("ok")
        self.assertEqual(codice, 1)


class TestFileReali(unittest.TestCase):
    """I file in dati/ devono essere coerenti: solo aziende della lista."""

    def test_fonti_manuali_solo_aziende_in_lista(self):
        with open("dati/aziende.json") as f:
            ids = {a["id"] for a in json.load(f)["aziende"]}
        with open("dati/fonti_manuali.json") as f:
            manuali = json.load(f)
        for k, fonti in manuali.items():
            if k.startswith("_"):
                continue
            self.assertIn(k, ids)
            for f in fonti:
                self.assertIn(f["tipo"], tf.LETTORI)


class TestSiti(unittest.TestCase):
    def test_fonte_da_url(self):
        import siti
        self.assertEqual(siti.fonte_da_url("https://jobs.lever.co/novaspace/abc"),
                         {"tipo": "lever", "slug": "novaspace"})
        self.assertEqual(siti.fonte_da_url("https://pno-group-europe.jobs.personio.com/job/1"),
                         {"tipo": "personio", "slug": "pno-group-europe", "dominio": "jobs.personio.com"})
        self.assertEqual(siti.fonte_da_url("https://www.welcometothejungle.com/fr/companies/lgi/jobs"),
                         {"tipo": "wttj", "slug": "lgi"})
        self.assertEqual(siti.fonte_da_url("https://thales.wd3.myworkdayjobs.com/fr-FR/Careers/job/x"),
                         {"tipo": "workday", "url": "https://thales.wd3.myworkdayjobs.com/fr-FR/Careers"})
        self.assertIsNone(siti.fonte_da_url("https://www.linkedin.com/company/x"))

    def test_id_come_nella_lista(self):
        import siti
        csv_testo = ("name;organizationURL\nEUROQUALITY SAS;www.euroquality.fr\n"
                     "EUROQUALITY;http://www.euroquality.fr/chi-siamo\nALTRA SRL;altra.it\n")
        self.assertEqual(siti.siti_da_cordis(csv_testo, {"euroquality"}),
                         {"euroquality": "https://www.euroquality.fr/"})

    def test_link_carriere(self):
        import siti
        html = """<nav><a href="/fr/nous-rejoindre">Nous rejoindre</a><a href="/contact">Contact</a></nav>
                  <footer><a href="https://jobs.lever.co/acme">Jobs</a></footer>"""
        portali, carriere = siti.link_carriere(html, "https://acme.fr/")
        self.assertEqual(portali, [{"tipo": "lever", "slug": "acme"}])
        self.assertEqual(carriere, "https://acme.fr/fr/nous-rejoindre")


class TestFalleCorrette(ConCartella):
    """Una prova per ogni falla trovata nella revisione del 26/10/2026."""

    def test_remote_sensing_non_e_da_remoto(self):
        self.assertEqual(tf.luogo({"titolo": "Remote Sensing Engineer", "location": "Toulouse"}), "ALTRO")
        self.assertEqual(tf.luogo({"titolo": "Data Analyst (Remote)", "location": "Madrid"}), "REMOTO")

    def test_solo_francia_e_sezione_a_parte(self):
        self.assertEqual(tf.luogo({"titolo": "x", "location": "France"}), "FR")
        self.assertEqual(tf.luogo({"titolo": "x", "location": "", "paese": "FR"}), "FR")
        self.assertEqual(tf.luogo({"titolo": "x", "location": "Toulouse, France"}), "ALTRO")
        self.assertEqual(tf.luogo({"titolo": "x", "location": "Paris, France"}), "PAR")

    def test_link_stabili_e_parole_intere(self):
        html = """<a href="/careers/junior-pm?utm_source=x&id=7">Junior Project Manager EU</a>
                  <a href="/international-cooperation">International cooperation news</a>
                  <a href="/careers/junior-pm?id=7&utm_source=y">Junior Project Manager EU</a>"""
        o = tf.estrai_link_annunci(html, "https://acme.it/careers")
        self.assertEqual([x["url"] for x in o], ["https://acme.it/careers/junior-pm?id=7"])

    def test_opportunita_di_finanziamento_non_e_carriere(self):
        import siti
        html = """<a href="/funding-opportunities">Funding opportunities</a>
                  <a href="/talent-programme">Talent programme</a>"""
        self.assertEqual(siti.link_carriere(html, "https://acme.eu/"), ([], ""))
        html2 = '<a href="/about/careers">Careers</a>'
        self.assertEqual(siti.link_carriere(html2, "https://acme.eu/")[1], "https://acme.eu/about/careers")

    def test_sede_non_indicata_solo_per_aziende_parigi_italia(self):
        az = dict(tn.carica_aziende())
        az["acme-de"] = {"id": "acme-de", "n": "Acme Berlin", "p": "DE", "k": "", "c": "B", "s": 50, "o": 0}
        seen = {"ids": {}, "fonti": ["lever:a", "lever:b"], "storico": []}
        o = lambda u: {"titolo": "Analyst", "location": "", "paese": "", "remoto": False, "url": u, "data": ""}
        nuove, stat = tn.seleziona(az, [("acme-de", {"tipo": "lever", "slug": "a"}, [o("u1")], None),
                                        ("acme-par", {"tipo": "lever", "slug": "b"}, [o("u2")], None)],
                                   seen, giorni_fa(0))
        self.assertEqual([x["azienda"] for x in nuove], ["acme-par"])
        self.assertEqual(stat["fuori_focus"], 1)

    def test_doppioni_tra_portali(self):
        az = tn.carica_aziende()
        seen = {"ids": {}, "fonti": ["lever:a", "workday:b"], "storico": []}
        o = lambda u: {"titolo": "Ingénieur Système", "location": "Vélizy", "paese": "", "remoto": False,
                       "url": u, "data": ""}
        nuove, stat = tn.seleziona(az, [("acme-par", {"tipo": "lever", "slug": "a"}, [o("u1")], None),
                                        ("acme-par", {"tipo": "workday", "url": "b"}, [o("u2")], None)],
                                   seen, giorni_fa(0))
        self.assertEqual(len(nuove), 1)
        self.assertEqual(stat["doppioni"], 1)

    def test_email_sotto_il_limite_di_gmail(self):
        az = tn.carica_aziende()
        nuove = [{"titolo": f"Offerta numero {i} con un titolo piuttosto lungo per occupare spazio",
                  "location": "Paris", "luogo": "PAR", "url": f"https://x/{i}", "data": giorni_fa(1),
                  "azienda": "acme-par" if i % 2 else "acme-it", "fonte_url": "https://x/tutte",
                  "gia_aperta": True} for i in range(3000)]
        stat = {"trovate": 3000, "fuori_focus": 0}
        html = tn.componi_email(nuove, az, {}, stat, [], 2)
        self.assertLessEqual(len(html.encode()), tn.MAX_EMAIL_BYTES)
        self.assertIn("vedi tutte", html)
        self.assertIn("https://x/tutte", html)

    def test_url_pubblico(self):
        self.assertEqual(tf.url_pubblico({"tipo": "lever", "slug": "novaspace"}), "https://jobs.lever.co/novaspace")
        self.assertEqual(tf.url_pubblico({"tipo": "personio", "slug": "pno", "dominio": "jobs.personio.com"}),
                         "https://pno.jobs.personio.com/")
        self.assertEqual(tf.url_pubblico({"tipo": "pagina", "url": "https://a.fr/jobs"}), "https://a.fr/jobs")

    def test_wttj_bloccato_prova_il_browser(self):
        html = '<a href="/fr/companies/acme/jobs/analyste_paris">Analyste</a>'
        with mock.patch.object(tf, "_get", side_effect=tf.FonteErrore("403")), \
             mock.patch.object(tf, "_html_con_browser", return_value=html):
            self.assertEqual(len(tf.wttj("acme")), 1)
        with mock.patch.object(tf, "_get", side_effect=tf.NonTrovata("404")):
            with self.assertRaises(tf.NonTrovata):
                tf.wttj("acme")


class TestErroriRicercaReale(unittest.TestCase):
    """Casi presi dall'elenco reale della ricerca del 26/10/2026."""

    def test_nome_identico_vero(self):
        self.assertFalse(tf.nome_uguale("Trust-It Services SRL", "Trust"))
        self.assertFalse(tf.nome_uguale("Hydrogen Europe Research", "Hydrogen"))
        self.assertTrue(tf.nome_uguale("Agorize", "Agorize"))
        self.assertTrue(tf.nome_uguale("Bpifrance", "BPIFRANCE"))

    def test_nome_forte(self):
        self.assertTrue(tf.nome_forte("Rina Consulting SPA", "RINA"))
        self.assertTrue(tf.nome_forte("Engie", "ENGIE Italia"))
        self.assertFalse(tf.nome_forte("Magellan Circle Italy SRL", "Magellan"))
        self.assertFalse(tf.nome_forte("Thales Six Gts France SAS", "Thales"))
        self.assertFalse(tf.nome_forte("Trust-It Services SRL", "Trust"))

    def test_nome_corto_va_da_verificare(self):
        az = {"n": "Thales Six Gts France SAS", "p": "FR"}
        francia = [tf._offerta("Ingénieur", "https://x/1", "Vélizy, France")]
        with mock.patch.object(tf, "_json", return_value={"content": [{"company": {"name": "Thales"}}]}), \
             mock.patch.object(tf, "leggi_fonte", return_value=francia):
            f = tf._prova("smartrecruiters", "thales", az)
        self.assertIn("da_verificare", f)

    def test_omonimo_con_annunci_altrove_scartato(self):
        az = {"n": "A.Spire", "p": "BE"}
        usa = [tf._offerta("Engineer", "https://x/1", "Boulder, CO", "US")]
        with mock.patch.object(tf, "_json", return_value={"name": "Spire"}), \
             mock.patch.object(tf, "leggi_fonte", return_value=usa):
            self.assertIsNone(tf._prova("greenhouse", "spire", az))

    def test_workday_stessa_chiave_in_ogni_lingua(self):
        a = tf.chiave_fonte({"tipo": "workday", "url": "https://thales.wd3.myworkdayjobs.com/fr-FR/Careers"})
        b = tf.chiave_fonte({"tipo": "workday", "url": "https://thales.wd3.myworkdayjobs.com/en-US/Careers"})
        self.assertEqual(a, b)

    def test_pagine_che_non_sono_carriere(self):
        import siti
        self.assertTrue(siti.sembra_articolo("https://www.insme.org/join-us-at-the-10th-insme-annual-meeting/"))
        self.assertFalse(siti.sembra_articolo("https://acme.fr/nous-rejoindre/"))
        adesione = "<h1>Join the network</h1><p>Become a member of our association, membership fees</p>"
        lavoro = "<h1>Careers</h1><p>Open positions: Junior consultant (full-time). Apply with your CV.</p>"
        self.assertFalse(siti.sembra_pagina_lavoro(adesione))
        self.assertTrue(siti.sembra_pagina_lavoro(lavoro))
        self.assertFalse(siti.RE_CARRIERE.search("/membership/join-us"))

    def test_sito_con_pagina_adesione_scartata(self):
        import siti
        home = '<a href="/nous-rejoindre/">Nous rejoindre</a>'
        adesione = "<p>Adhérer au réseau : cotisation annuelle des membres</p>"
        pagine = {"https://rete.fr/": home, "https://rete.fr/nous-rejoindre/": adesione}
        with mock.patch.object(siti, "_html", side_effect=lambda u: (pagine[u], u)):
            self.assertEqual(siti.trova_fonti_sito("https://rete.fr/"), [])
        pagine["https://rete.fr/nous-rejoindre/"] = "<p>Nous recrutons : stage et CDI, postuler ici</p>"
        with mock.patch.object(siti, "_html", side_effect=lambda u: (pagine[u], u)):
            self.assertEqual(siti.trova_fonti_sito("https://rete.fr/")[0]["url"], "https://rete.fr/nous-rejoindre/")


class TestErroriTerzaRicerca(unittest.TestCase):
    def test_bacheche_di_rete_e_teamtailor(self):
        import siti
        self.assertTrue(siti.bacheca_di_rete("https://www.axelera.org/fr/offres-d-emploi-du-reseau"))
        self.assertTrue(siti.bacheca_di_rete("https://www.polymeris.fr/bourse-a-l-emploi.html"))
        self.assertFalse(siti.bacheca_di_rete("https://www.cls.fr/carrieres/"))
        self.assertIsNone(siti.fonte_da_url("https://www.teamtailor.com/jobs"))
        self.assertEqual(siti.fonte_da_url("https://torrecid.teamtailor.com/jobs/123"),
                         {"tipo": "pagina", "url": "https://torrecid.teamtailor.com/jobs"})

    def test_articolo(self):
        import siti
        self.assertTrue(siti.sembra_articolo("https://euronovia.eu/recrutement-apprenti-financements-europeens/"))
        self.assertFalse(siti.sembra_articolo("https://www.laborelec.com/jobs_open_positions/"))

    def test_carriere_che_rimanda_alla_home(self):
        import siti
        home = '<a href="/careers">Careers</a>'
        with mock.patch.object(siti, "_html", side_effect=lambda u: (home, "https://www.actia-asso.eu/")):
            self.assertEqual(siti.trova_fonti_sito("https://www.actia-asso.eu/"), [])


class TestErroriQuartaRicerca(unittest.TestCase):
    def test_redirect_wordpress_verso_articolo(self):
        import siti
        home = "<p>Accueil</p>"
        articolo = "<p>Nous recrutons un apprenti : candidature, CV, contrat</p>"

        def finto(u):
            if u.rstrip("/") == "https://euronovia.eu":
                return home, "https://euronovia.eu/"
            return articolo, "https://euronovia.eu/recrutement-apprenti-financements-europeens/"
        with mock.patch.object(siti, "_html", side_effect=finto):
            self.assertEqual(siti.trova_fonti_sito("https://euronovia.eu/"), [])


if __name__ == "__main__":
    unittest.main()
