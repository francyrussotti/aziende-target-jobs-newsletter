"""Test offline della newsletter: nessuna rete, nessuna email.
Avvio:  python -m unittest -v test_newsletter
"""
import json
import os
import sys
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
        with mock.patch.object(siti, "_html", side_effect=lambda u, **_: (pagine[u], u)):
            self.assertEqual(siti.trova_fonti_sito("https://rete.fr/"), [])
        pagine["https://rete.fr/nous-rejoindre/"] = "<p>Nous recrutons : stage et CDI, postuler ici</p>"
        with mock.patch.object(siti, "_html", side_effect=lambda u, **_: (pagine[u], u)):
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

    def test_sito_irraggiungibile_non_e_senza_carriere(self):
        import siti
        with mock.patch.object(siti, "_html", side_effect=tf.FonteErrore("timeout")):
            self.assertIsNone(siti.trova_fonti_sito("https://lento.eu/"))

    def test_carriere_che_rimanda_alla_home(self):
        import siti
        home = '<a href="/careers">Careers</a>'
        with mock.patch.object(siti, "_html", side_effect=lambda u, **_: (home, "https://www.actia-asso.eu/")):
            self.assertEqual(siti.trova_fonti_sito("https://www.actia-asso.eu/"), [])


class TestErroriQuartaRicerca(unittest.TestCase):
    def test_redirect_wordpress_verso_articolo(self):
        import siti
        home = "<p>Accueil</p>"
        articolo = "<p>Nous recrutons un apprenti : candidature, CV, contrat</p>"

        def finto(u, **_):
            if u.rstrip("/") == "https://euronovia.eu":
                return home, "https://euronovia.eu/"
            return articolo, "https://euronovia.eu/recrutement-apprenti-financements-europeens/"
        with mock.patch.object(siti, "_html", side_effect=finto):
            self.assertEqual(siti.trova_fonti_sito("https://euronovia.eu/"), [])


class TestScopriFonti(unittest.TestCase):
    """scopri_fonti.main con rete finta: regole, unione, decisioni manuali."""

    def setUp(self):
        import scopri_fonti, newsletter
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        p = lambda n: os.path.join(self.dir.name, n)
        for mod in (scopri_fonti, newsletter):
            for attr, nome in [("AZIENDE_FILE", "aziende.json"), ("FONTI_FILE", "fonti.json"),
                               ("FONTI_MANUALI_FILE", "fonti_manuali.json")]:
                if hasattr(mod, attr):
                    m = mock.patch.object(mod, attr, p(nome)); m.start(); self.addCleanup(m.stop)
        with open(p("aziende.json"), "w") as f:
            json.dump({"aziende": [{"id": "a", "n": "Acme", "p": "FR", "k": "PAR"},
                                   {"id": "m", "n": "Manuale", "p": "IT", "k": "IT"}]}, f)
        with open(p("fonti_manuali.json"), "w") as f:
            json.dump({"m": []}, f)
        self.p, self.sf = p, scopri_fonti

    def lancia(self, trovate):
        with mock.patch.object(self.sf.siti, "_leggi_json", create=True), \
             mock.patch.object(self.sf, "siti") as finto_siti, \
             mock.patch.object(self.sf.tf, "scopri", return_value=trovate), \
             mock.patch.object(sys, "argv", ["scopri_fonti.py", "--minuti", "1"]):
            finto_siti.SITI_FILE = self.p("siti.json")
            self.sf.main()
        with open(self.p("fonti.json")) as f:
            return json.load(f)

    def test_unione_e_regole(self):
        d = self.lancia([{"tipo": "lever", "slug": "acme", "verifica": "x"}])
        self.assertEqual(d["regole"], self.sf.REGOLE)
        self.assertEqual(list(d["fonti"]), ["a"])                 # "m" ha decisione manuale
        d = self.lancia([])                                       # sito lento: niente trovato
        self.assertEqual([f["slug"] for f in d["fonti"]["a"]], ["acme"])
        d["regole"] = 0                                           # regole cambiate
        with open(self.p("fonti.json"), "w") as f:
            json.dump(d, f)
        d = self.lancia([])
        self.assertEqual(d["fonti"], {})


    def test_solo_nuove(self):
        self.lancia([{"tipo": "lever", "slug": "acme", "verifica": "x"}])   # "a" controllata
        with open(self.p("aziende.json"), "w") as f:
            json.dump({"aziende": [{"id": "a", "n": "Acme", "p": "FR", "k": "PAR"},
                                   {"id": "b", "n": "Beta", "p": "FR", "k": "PAR"}]}, f)
        cercate = []
        with mock.patch.object(self.sf, "siti") as finto_siti, \
             mock.patch.object(self.sf.tf, "scopri", side_effect=lambda az: cercate.append(az["id"]) or []), \
             mock.patch.object(sys, "argv", ["scopri_fonti.py", "--nuove"]):
            finto_siti.SITI_FILE = self.p("siti.json")
            self.sf.main()
        self.assertEqual(cercate, ["b"])


class TestImportaAziende(unittest.TestCase):
    def test_solo_data_cambiata_file_invariato(self):
        import importa_aziende as ia
        az = [{"id": f"a{i}", "n": f"Azienda {i}", "s": 50} for i in range(60)]
        with tempfile.TemporaryDirectory() as d:
            out, html = os.path.join(d, "aziende.json"), os.path.join(d, "p.html")
            def pagina(data):
                with open(html, "w") as f:
                    f.write('<script type="application/json" id="dati">'
                            + json.dumps({"generato": data, "aziende": az}) + "</script>")
            pagina("26/10/2026")
            with mock.patch.object(sys, "argv", ["x", "--html", html, "--out", out]):
                ia.main()
                prima = open(out).read()
                pagina("27/10/2026")
                ia.main()
            self.assertEqual(open(out).read(), prima)

    def test_differenze(self):
        import importa_aziende as ia
        nuove, uscite = ia.differenze({"a": "A", "b": "B"}, [{"id": "b"}, {"id": "c"}])
        self.assertEqual((nuove, uscite), (["c"], ["a"]))


class TestErroriProvaCompleta(unittest.TestCase):
    """Dalla prova di tutte le fonti del 26/10/2026 (102 fonti, 3090 offerte)."""

    def test_pagine_dei_grandi_gruppi_senza_spazzatura(self):
        html = """<a href="/careers/life-at-nokia/">Life at Nokia</a>
          <a href="/careers/students-and-graduates/">Students and graduates</a>
          <a href="/careers/our-locations/portugal/">Portugal</a>
          <a href="https://jobs.siemens.com/en_US/externaljobs">Explore all jobs</a>
          <a href="/careers/job/123">Ingénieur système F/H</a>
          <a href="/careers/job/124">Chargé de projets européens</a>
          <a href="/jobs/werkstudent-5">Werkstudent Marketing (m/w/d)</a>"""
        o = tf.estrai_link_annunci(html, "https://www.nokia.com/careers/")
        self.assertEqual([x["titolo"] for x in o], ["Ingénieur système F/H", "Chargé de projets européens",
                                                     "Werkstudent Marketing (m/w/d)"])

    def test_workday_lingua_breve(self):
        import siti
        self.assertIsNone(siti.fonte_da_url("https://repsol.wd3.myworkdayjobs.com/es"))
        self.assertEqual(siti.fonte_da_url("https://repsol.wd3.myworkdayjobs.com/es/Repsol/job/x"),
                         {"tipo": "workday", "url": "https://repsol.wd3.myworkdayjobs.com/es/Repsol"})
        with self.assertRaises(tf.FonteErrore):
            tf.workday("https://repsol.wd3.myworkdayjobs.com/es")
        self.assertEqual(tf.chiave_fonte({"tipo": "workday", "url": "https://a.wd3.myworkdayjobs.com/es/Ext"}),
                         tf.chiave_fonte({"tipo": "workday", "url": "https://a.wd3.myworkdayjobs.com/Ext"}))

    def test_personio_senza_xml(self):
        html = """<a href="/job/111?language=de"><span>Referent*in Öko-Landbau</span><span>Gräfelfing</span></a>
                  <a href="/job/111">doppione</a>"""
        risposte = [tf.NonTrovata("404"), FintaRisposta(testo=html)]
        with mock.patch.object(tf, "_get", side_effect=risposte):
            o = tf.personio("naturland-e-v")
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["titolo"], o[0]["location"]), ("Referent*in Öko-Landbau", "Gräfelfing"))
        self.assertEqual(o[0]["url"], "https://naturland-e-v.jobs.personio.de/job/111")


class TestSecondaProvaCompleta(unittest.TestCase):
    """Dalla seconda prova di tutte le fonti (105 funzionanti, log letto per intero)."""

    def test_comuni_ile_de_france(self):
        for loc in ["Le Plessis Robinson", "Linas, IDF, France", "Brétigny-sur-Orge", "Les Mureaux",
                    "Montigny-le-Bretonneux", "92350 Le Plessis-Robinson", "Clamart"]:
            self.assertEqual(tf.luogo({"titolo": "x", "location": loc}), "PAR", loc)
        self.assertEqual(tf.luogo({"titolo": "x", "location": "Toulouse"}), "ALTRO")

    def test_operat_solo_come_mestiere(self):
        self.assertFalse(tf.RE_TITOLO_LAVORO.search("Operations"))
        self.assertTrue(tf.RE_TITOLO_LAVORO.search("Opérateur de production F/H"))

    def test_sede_dal_titolo(self):
        self.assertEqual(tf.luogo({"titolo": "R&D Project Manager Rome Italy", "location": ""}), "IT")
        self.assertEqual(tf.luogo({"titolo": "Chargé de mission – Paris", "location": ""}), "PAR")

    def test_link_non_annunci(self):
        html = """<a href="/careers/operations/">Operations</a>
          <a href="/privacy.pdf">Data Privacy Notice for employees, workers, directors and consultants</a>
          <a href="/meet-nils">Meet Nils Libert, Associate Scientist in R&D</a>
          <a href="/careers/pupils/">Pupils Find your apprenticeship with a future. read more</a>
          <a href="/careers/fellowships">SYNYO Fellowships</a>
          <a href="/jobs?search=Engineer">Engineer</a>
          <a href="/careers/trainee">Trainee controller recruitment now open</a>
          <a href="/jobs/rd-pm">R&D Project Manager R&D Project Manager Rome Italy More Details</a>"""
        o = tf.estrai_link_annunci(html, "https://x.eu/careers")
        self.assertEqual([x["titolo"] for x in o], ["R&D Project Manager Rome Italy"])

    def test_candidature_generiche_escluse_da_ogni_fonte(self):
        offerte = [tf._offerta("Spontaneous Application", "u1"), tf._offerta("Open application", "u2"),
                   tf._offerta("¡Únete a nuestro equipo!/ Join our team!", "u3"),
                   tf._offerta("Join Johnson Matthey Royston!", "u5"),
                   tf._offerta("Head of Asia Pacific", "u4")]
        with mock.patch.dict(tf.LETTORI, {"recruitee": lambda **_: offerte}):
            self.assertEqual([o["titolo"] for o in tf.leggi_fonte({"tipo": "recruitee", "slug": "uitp"})],
                             ["Head of Asia Pacific"])


class TestDiagnosi(unittest.TestCase):
    """Dalla diagnosi delle 42 aziende prioritarie senza fonte (26/10/2026)."""

    def test_wttj_con_browser_e_nome_dalla_pagina(self):
        html = """<html><head><title>Hello Tomorrow : offres d'emploi | Welcome to the Jungle</title></head>
                  <body><h1>Hello Tomorrow</h1>
                  <a href="/fr/companies/hello-tomorrow/jobs/consultant_paris">Consultant deep tech</a></body></html>"""
        self.assertIn("Hello Tomorrow", tf.nomi_pagina_wttj(html))
        with mock.patch.object(tf, "_html_con_browser", return_value=html):
            f = tf._prova("wttj", "hello-tomorrow", {"n": "Hello Tomorrow", "p": "FR"})
        self.assertEqual((f["tipo"], f["slug"]), ("wttj", "hello-tomorrow"))
        self.assertNotIn("da_verificare", f)
        altra = html.replace("Hello Tomorrow", "Goodbye Yesterday")
        with mock.patch.object(tf, "_html_con_browser", return_value=altra):
            self.assertIsNone(tf._prova("wttj", "hello-tomorrow", {"n": "Hello Tomorrow", "p": "FR"}))

    def test_wttj_solo_per_aziende_di_parigi(self):
        provati = []
        with mock.patch.object(tf, "_prova", side_effect=lambda t, s, a: provati.append(t)):
            tf.scopri({"n": "Acme Lyon", "p": "FR", "k": ""})
            self.assertNotIn("wttj", provati)
            tf.scopri({"n": "Acme Paris", "p": "FR", "k": "PAR"})
            self.assertIn("wttj", provati)

    def test_home_non_e_pagina_carriere(self):
        import siti
        html = '<a href="https://www.engie.com/">Carrières</a><a href="/fr/carrieres">Nous rejoindre</a>'
        self.assertEqual(siti.link_carriere(html, "https://www.engie.com/")[1], "https://www.engie.com/fr/carrieres")


class TestInvioEmail(unittest.TestCase):
    """Prima newsletter reale (26/10): Gmail chiudeva la connessione."""

    def test_segreti_ripuliti(self):
        env = {"GMAIL_MITTENTE": " fra@gmail.com\n", "GMAIL_PASSWORD": "abcd efgh ijkl mnop\n",
               "EMAIL_DESTINATARIO": "a@x.it, b@y.it"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(tn._segreti(), ("fra@gmail.com", "abcdefghijklmnop", "a@x.it, b@y.it"))

    def test_porta_di_riserva(self):
        env = {"GMAIL_MITTENTE": "fra@gmail.com", "GMAIL_PASSWORD": "abcdefghijklmnop",
               "EMAIL_DESTINATARIO": "a@x.it"}
        ok = mock.MagicMock()
        ok.__enter__.return_value = ok
        porte = []

        def finto(porta):
            porte.append(porta)
            if porta == 465:
                raise tn.smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
            return ok
        with mock.patch.dict(os.environ, env), mock.patch.object(tn, "_smtp", side_effect=finto), \
             mock.patch.object(tn.time, "sleep"):
            self.assertEqual(tn.invia_email("<p>x</p>", "oggetto"), "ok")
        self.assertEqual(porte, [465, 587])
        ok.login.assert_called_once_with("fra@gmail.com", "abcdefghijklmnop")


class TestFiltroLingua(unittest.TestCase):
    """Fra parla italiano, inglese, spagnolo; francese di base (si segnala, non si esclude)."""

    def v(self, titolo, testo=""):
        import lingue
        return lingue.valuta(titolo, testo)

    def test_richieste_escluse(self):
        self.assertEqual(self.v("PM", "Requirements: fluent German and English are required.")[:2],
                         (True, "richiesto tedesco"))
        self.assertTrue(self.v("Sales", "Native Dutch speaker")[0])
        self.assertTrue(self.v("C", "Uitstekende beheersing van het Nederlands en Engels.")[0])
        self.assertTrue(self.v("C", "Deutsch fließend in Wort und Schrift")[0])
        self.assertTrue(self.v("Projektleiter (m/w/d)")[0])

    def test_facoltative_o_alternative_restano(self):
        self.assertFalse(self.v("PM", "Languages: English (fluent), German is a plus.")[0])
        self.assertFalse(self.v("C", "You speak English or German fluently.")[0])
        self.assertFalse(self.v("I", "Anglais courant exigé, allemand apprécié.")[0])
        self.assertFalse(self.v("C", "Ottima conoscenza dell'inglese; il tedesco costituisce titolo preferenziale.")[0])
        self.assertFalse(self.v("A", "We are a German company with offices in Paris. You are curious.")[0])
        self.assertFalse(self.v("Pre-sales", "You will polish our documents, fluent English required.")[0])

    def test_francese_richiesto_in_annuncio_inglese_segnalato(self):
        self.assertEqual(self.v("Project Engineer", "Fluent French and English are required."),
                         (False, "", True))

    def test_annuncio_tutto_in_francese_escluso(self):
        fr = ("Nous recherchons un ingénieur pour notre équipe à Paris. Vous serez en charge de la gestion "
              "des projets avec nos clients et de la coordination des équipes. Vous avez une expérience dans "
              "le domaine et vous aimez travailler en équipe. Nous vous offrons un environnement stimulant "
              "avec des perspectives d'évolution au sein du groupe et des avantages.")
        self.assertEqual(self.v("Ingénieur projet", fr)[:2], (True, "annuncio in francese"))

    def test_titolo_spagnolo_con_descrizione_francese_resta(self):
        fr = ("Nous recherchons un ingénieur pour notre équipe à Paris. Vous serez en charge de la gestion "
              "des projets avec nos clients et de la coordination des équipes. Vous avez une expérience dans "
              "le domaine et vous aimez travailler en équipe. Nous vous offrons un environnement stimulant "
              "avec des perspectives d'évolution au sein du groupe et des avantages.")
        self.assertFalse(self.v("Experto/a Técnico/a Freelance – Documentación de Proyectos", fr)[0])
        self.assertTrue(self.v("Chef de projet (H/F)", fr)[0])
        self.assertTrue(self.v("Technicien de Maintenance H/F", fr)[0])

    def test_titolo_francese_senza_descrizione(self):
        self.assertTrue(self.v("Ingénieur Conception mécanique – CDI – Pessac (H/F)")[0])
        self.assertTrue(self.v("Chef de projet innovation")[0])
        self.assertFalse(self.v("Software Engineer (H/F)")[0])
        self.assertFalse(self.v("Business Developer")[0])
        # con una descrizione in inglese conta la descrizione, non il titolo
        en = " ".join(["You will work with the team on the projects and the clients of our company."] * 5)
        self.assertFalse(self.v("Chargé de projet (H/F)", en)[0])

    def test_annuncio_scritto_in_tedesco(self):
        de = ("Wir suchen eine engagierte Person für unser Team in München. Du bist verantwortlich für "
              "die Planung und Umsetzung von Projekten mit unseren Kunden. Wir bieten dir ein spannendes "
              "Umfeld, flexible Arbeitszeiten und die Möglichkeit, dich weiterzuentwickeln. Deine Aufgaben "
              "sind vielfältig und du arbeitest eng mit den Kollegen zusammen. Wir freuen uns auf deine "
              "Bewerbung und sind gespannt auf dich und deine Ideen für das Team bei uns.")
        self.assertEqual(self.v("Projektmanager", de)[:2], (True, "annuncio in tedesco"))

    def test_filtra_lingue(self):
        nuove = [{"azienda": "a", "titolo": "PM", "testo": "Fluent German required."},
                 {"azienda": "a", "titolo": "Chef de projet", "testo": "Fluent French is required."},
                 {"azienda": "a", "titolo": "Analyst", "testo": "", "dettaglio": "x"},
                 {"azienda": "a", "titolo": "Engineer", "url": "https://x/1", "dettaglio": "d"}]
        stat = {}
        with mock.patch.object(tf, "descrizione", return_value="Fluent Dutch required") as d:
            tenute = tn.filtra_lingue(nuove, stat)
        d.assert_called_once()                       # solo l'offerta senza testo
        self.assertEqual([o["titolo"] for o in tenute], ["Chef de projet", "Analyst"])
        self.assertTrue(tenute[0]["francese"])
        self.assertNotIn("testo", tenute[1])
        self.assertNotIn("dettaglio", tenute[1])
        self.assertEqual((stat["lingua"], stat["senza_testo"]), (2, 1))

    def test_lettori_con_descrizione(self):
        lever = [{"text": "PM", "hostedUrl": "u", "categories": {"location": "Paris"},
                  "descriptionPlain": "Intro", "lists": [{"text": "Requirements", "content": "<li>Fluent German</li>"}],
                  "additionalPlain": ""}]
        with mock.patch.object(tf, "_json", return_value=lever):
            o = tf.lever("acme")[0]
        self.assertIn("Fluent German", o["testo"])
        wd = {"total": 1, "facets": [], "jobPostings": [{"title": "Ing", "externalPath": "/job/Paris/Ing_R1",
                                                          "locationsText": "Paris", "postedOn": "Posted Today"}]}
        with mock.patch.object(tf, "_json", return_value=wd):
            o = tf.workday("https://thales.wd3.myworkdayjobs.com/fr-FR/Careers")[0]
        self.assertEqual(o["dettaglio"], "https://thales.wd3.myworkdayjobs.com/wday/cxs/thales/Careers/job/Paris/Ing_R1")
        self.assertNotIn("testo", o)
        with mock.patch.object(tf, "_json", return_value={"jobPostingInfo": {"jobDescription": "<p>Fluent <b>German</b></p>"}}):
            self.assertEqual(tf.descrizione(o), "Fluent German")


class TestRemotoFuoriEuropa(unittest.TestCase):
    def test_remoto_brasile_non_mostrato(self):
        self.assertEqual(tf.luogo({"titolo": "Engineer", "location": "Belo Horizonte, MG, Brazil",
                                   "paese": "BR", "remoto": True}), "ALTRO")
        self.assertEqual(tf.luogo({"titolo": "Engineer", "location": "Remote - USA", "remoto": True}), "ALTRO")
        self.assertEqual(tf.luogo({"titolo": "Engineer", "location": "Remote", "paese": "ES", "remoto": True}), "REMOTO")
        self.assertEqual(tf.luogo({"titolo": "Engineer", "location": "", "remoto": True}), "REMOTO")


if __name__ == "__main__":
    unittest.main()
