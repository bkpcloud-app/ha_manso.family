import importlib.util
from pathlib import Path
import unittest
import aiohttp
from aiohttp import web

spec = importlib.util.spec_from_file_location("va_api", Path(__file__).parents[1] / "custom_components/vestibulare_elshaday/api.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

CARD = '<div>Aula 10/03/2026 ─ <span class="">Professor Exemplo</span><div class="limite-linha-va-card">\n<span>Atividade &amp; teste</span></div><small>até 12/03/2026 12:00</small></div>'
EXPECTED = {"disciplina":"Arte", "data":"10/03/2026", "professor":"Professor Exemplo", "descricao":"Atividade & teste", "prazo":"12/03/2026 12:00"}
EMPTY = "<div>Nenhum planejamento encontrado</div>"

class Parser(unittest.TestCase):
    def test_reference(self):
        self.assertEqual(a.parse_html(CARD, "Arte"), [EXPECTED])
    def test_empty(self):
        self.assertEqual(a.parse_html(EMPTY, "Arte"), [])
    def test_unknown(self):
        with self.assertRaises(a.FormatError):
            a.parse_html("<div>erro</div>", "Arte")
    def test_session(self):
        with self.assertRaises(a.AuthError):
            a.parse_html('<input type="password">', "Arte")
    def test_no_due(self):
        items = a.parse_html(CARD.replace("<small>até 12/03/2026 12:00</small>", "") + CARD, "Arte")
        self.assertEqual([i["prazo"] for i in items], ["", "12/03/2026 12:00"])
    def test_malformed(self):
        with self.assertRaises(a.FormatError):
            a.parse_html(CARD.replace('class=""','class="invalid"'), "Arte")
    def test_submission_probe_does_not_infer_delivery_from_green_check(self):
        sample = CARD.replace("<small>até", '<i class="fa fa-check-circle text-success" title="Concluída"></i><small>até')
        evidence = a.inspect_submission_markers(sample, "Arte")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["status_entrega"], "nao_verificado")
        self.assertNotIn("indicadores_html", evidence[0])
        self.assertTrue(any("check-circle" in x for x in a.inspect_visual_markers(sample)))
        self.assertEqual(a.parse_html(sample, "Arte"), [EXPECTED])

    def test_submission_probe_keeps_cards_separate(self):
        first = CARD.replace("<small>até", '<i class="fa fa-check text-success"></i><small>até')
        second = CARD.replace("Aula 10/03/2026", "Aula 11/03/2026")
        evidence = a.inspect_submission_markers(first + second, "Arte")
        self.assertEqual([x["aula"] for x in evidence], ["10/03/2026", "11/03/2026"])
        self.assertTrue(all("indicadores_html" not in x for x in evidence))
        self.assertTrue(all(x["status_entrega"] == "nao_verificado" for x in evidence))

    def test_green_check_does_not_prove_submission(self):
        check = '<i class="fa fa-check-circle text-success" title="Concluído"></i>'
        read = CARD.replace("<small>até", '<div class="va-card-lido-inferior va-plan-card-status">'
            + check + '</div><small>até')
        unread = CARD.replace("<small>até", '<div class="va-card-nao-lido-inferior va-plan-card-status">'
            + check + '</div><small>até')
        for name, sample in (("Arte", read), ("Língua Portuguesa", unread)):
            marker = a.inspect_submission_markers(sample, name)[0]
            self.assertEqual(marker["status_entrega"], "nao_verificado")
            self.assertNotIn("indicadores_visuais", marker)
            self.assertTrue(any("check" in v for v in a.inspect_visual_markers(sample)))
        self.assertTrue(any("va-card-lido-inferior" in v for v in a.inspect_visual_markers(read)))
        self.assertTrue(any("va-card-nao-lido-inferior" in v for v in a.inspect_visual_markers(unread)))

    def test_visual_markers_redact_private_data(self):
        html = (
            '<img src="/assets/check.svg?token=PRIVATE" '
            'alt="Verificado para estudante PRIVATE"/>'
            '<span class="va-status-success check-PRIVATE" data-status="concluido" '
            'data-username="PRIVATE" data-token="PRIVATE">PRIVATE</span>'
        )
        markers = a.inspect_visual_markers(html)
        self.assertTrue(markers)
        self.assertTrue(any("concluido" in m for m in markers))
        self.assertNotIn("PRIVATE", repr(markers))
        self.assertNotIn("token", repr(markers))

    def test_status_negation_is_not_lost(self):
        negative = a.inspect_visual_markers(
            '<span data-status="não entregue"></span><i title="not-completed"></i>')
        positive = a.inspect_visual_markers('<span data-status="entregue"></span>')
        self.assertTrue(any("nao_entregue" in v for v in negative))
        self.assertTrue(any("nao_concluida" in v for v in negative))
        self.assertFalse(any("nao_entregue" in v for v in positive))

    def test_card_headers_not_misattributed(self):
        html = ('<div class="va-card-lido-inferior">Aula 10/03/2026</div>'
                '<div class="va-card-nao-lido-inferior">Aula 11/03/2026</div>')
        cards = a.inspect_submission_markers(html, "Arte")
        self.assertEqual(len(cards), 2)
        self.assertTrue(all("indicadores_html" not in c for c in cards))
        self.assertTrue(all("indicadores_visuais" not in c for c in cards))
        self.assertEqual(cards[0]["status_entrega"], "nao_verificado")

    def test_portal_url(self):
        self.assertEqual(a.normalize_portal("https://escola.vestibulare.com.br/"), "https://escola.vestibulare.com.br/va")
        for url in ["http://escola.vestibulare.com.br", "https://example.invalid", "https://escola.vestibulare.com.br.example.invalid", "https://x@y.vestibulare.com.br"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                a.normalize_portal(url)

class HTTP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mode = "ok"
        self.ids = []
        app = web.Application()
        app.router.add_post("/va/ajax/verificaLogin.php", self.login)
        app.router.add_get("/va/pages/planejamento/ajax/planejamentos-lista.php", self.listing)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        self.client = a.PortalClient(self.session, "dummy@example.invalid", "fake&pass", f"http://127.0.0.1:{port}/va")
    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
    async def login(self, req):
        self.assertEqual(dict(await req.post()), {"login":"dummy@example.invalid","senha":"fake&pass","ipAcesso":""})
        self.assertEqual(req.query["app"], "off")
        self.assertEqual(req.headers["User-Agent"], a.UA)
        resp = web.json_response({"status":1 if self.mode == "auth" else 0})
        resp.set_cookie("session", "test")
        return resp
    async def listing(self, req):
        self.assertEqual(req.cookies.get("session"), "test")
        self.assertEqual(req.query["anoSelecionado"], "2026")
        self.assertEqual(req.query["ordenacaoPlanejamentos"], "abertos")
        self.assertEqual(req.query["todasAsTurmas"], "true")
        id_ = int(req.query["idDisciplina"])
        self.ids.append(id_)
        if self.mode == "http" and id_ == 21:
            return web.Response(status=503)
        if self.mode == "redirect":
            raise web.HTTPFound("/login.php")
        if self.mode == "unknown" and id_ == 21:
            return web.Response(text="unexpected")
        return web.Response(text=CARD if id_ == 1 and self.mode != "empty" else EMPTY)
    async def test_collect(self):
        self.assertEqual(await self.client.collect(2026), [EXPECTED])
        self.assertEqual(self.ids, list(a.DISCIPLINAS))
        self.assertEqual(len(self.client.last_counts), 11)
        self.assertEqual(self.client.last_counts["Arte"], 1)
        self.assertEqual(sum(self.client.last_counts.values()), 1)
        self.assertEqual(len(self.client.last_visual_diagnostics), 11)
        self.assertEqual(self.client.last_visual_diagnostics[0]["disciplina"], "Arte")
        self.assertEqual(self.client.last_counts["Matemática"], 0)
    async def test_empty(self):
        self.mode = "empty"
        self.assertEqual(await self.client.collect(2026), [])
        self.assertEqual(len(self.ids), 11)
        self.assertEqual(len(self.client.last_counts), 11)
        self.assertEqual(sum(self.client.last_counts.values()), 0)
    async def test_auth(self):
        self.mode = "auth"
        with self.assertRaises(a.AuthError):
            await self.client.collect(2026)
        self.assertEqual(self.ids, [])
    async def test_http(self):
        self.mode = "http"
        with self.assertRaises(a.PortalError):
            await self.client.collect(2026)
        self.assertEqual(len(self.client.last_counts), 1)
    async def test_redirect(self):
        self.mode = "redirect"
        with self.assertRaises(a.PortalError):
            await self.client.collect(2026)
    async def test_unknown(self):
        self.mode = "unknown"
        with self.assertRaises(a.FormatError):
            await self.client.collect(2026)
