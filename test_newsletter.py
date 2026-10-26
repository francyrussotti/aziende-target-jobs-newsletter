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
        self.assertFalse(tf.nome_corrisponde("Innova SRL", "Innovaphone"))
        self.assertFalse(tf.nome_corrisponde("Gac", "Gucci"))
        self.assertFalse(tf.nome_corrisponde("Erdyn Consultants SAS", "Capgemini Consulting"))

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

    def test_workday_facet_e_pagine(self):
        facets = [{"facetParameter": "locationCountry", "values": [
            {"id": "fr1", "descriptor": "France"}, {"id": "de1", "descriptor": "Germany"},
            {"id": "it1", "descriptor": "Italy"}]}]
        righe = lambda n: [{"title": f"Job {i}", "externalPath": f"/job/{i}",
                            "locationsText": "Paris", "postedOn": "Posted 2 Days Ago"} for i in range(n)]
        risposte = [{"total": 9999, "facets": facets, "jobPostings": righe(20)},
                    {"total": 25, "jobPostings": righe(20)}, {"jobPostings": righe(5)}]
        with mock.patch.object(tf, "_json", side_effect=risposte) as j:
            o = tf.workday("https://thales.wd3.myworkdayjobs.com/fr-FR/Careers")
        self.assertEqual(len(o), 25)
        api, kw = j.call_args_list[1][0][0], j.call_args_list[1][1]
        self.assertEqual(api, "https://thales.wd3.myworkdayjobs.com/wday/cxs/thales/Careers/jobs")
        self.assertEqual(kw["json"]["appliedFacets"], {"locationCountry": ["fr1", "it1"]})
        self.assertEqual(o[0]["url"], "https://thales.wd3.myworkdayjobs.com/fr-FR/Careers/job/0")
        self.assertEqual(o[0]["data"], giorni_fa(2))

    def test_wttj(self):
        html = """<a href="/fr/companies/hello-tomorrow/jobs/deep-tech-intern_paris_HT_V1">Deep Tech Intern</a>
                  <a href="/fr/companies/hello-tomorrow/jobs/deep-tech-intern_paris_HT_V1">doppione</a>
                  <a href="/fr/companies/hello-tomorrow/jobs/spontaneous-application_paris">Spontanea</a>
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
                   self.offerta("senza-data"), self.offerta("madrid", loc="Madrid", data=giorni_fa(1))]
        nuove, stat = tn.seleziona(az, [("acme-par", fonte, offerte, None)], seen, giorni_fa(0))
        self.assertEqual([o["titolo"] for o in nuove], ["recente"])
        self.assertEqual((stat["vecchie"], stat["iniziali"], stat["fuori_focus"]), (1, 1, 1))
        # Run successiva: le offerte note non tornano, una nuova senza data sì
        nuove, _ = tn.seleziona(az, [("acme-par", fonte, offerte + [self.offerta("nuova")], None)],
                                seen, giorni_fa(0))
        self.assertEqual([o["titolo"] for o in nuove], ["nuova"])

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
        ids = {a["id"] for a in json.load(open("dati/aziende.json"))["aziende"]}
        manuali = json.load(open("dati/fonti_manuali.json"))
        for k, fonti in manuali.items():
            if k.startswith("_"):
                continue
            self.assertIn(k, ids)
            for f in fonti:
                self.assertIn(f["tipo"], tf.LETTORI)


if __name__ == "__main__":
    unittest.main()
