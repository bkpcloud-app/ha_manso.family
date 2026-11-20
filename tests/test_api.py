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
        self.assertTrue(any("check-circle" in x for x in evidence[0]["indicadores_html"]))
        self.assertEqual(a.parse_html(sample, "Arte"), [EXPECTED])

    def test_submission_probe_keeps_cards_separate(self):
        first = CARD.replace("<small>até", '<i class="fa fa-check text-success"></i><small>até')
        second = CARD.replace("Aula 10/03/2026", "Aula 11/03/2026")
        evidence = a.inspect_submission_markers(first + second, "Arte")
        self.assertEqual([x["aula"] for x in evidence], ["10/03/2026", "11/03/2026"])
        self.assertTrue(evidence[0]["indicadores_html"])
        self.assertFalse(evidence[1]["indicadores_html"])
        self.assertTrue(all(x["status_entrega"] == "nao_verificado" for x in evidence))

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
    async def test_empty(self):
        self.mode = "empty"
        self.assertEqual(await self.client.collect(2026), [])
        self.assertEqual(len(self.ids), 11)
    async def test_auth(self):
        self.mode = "auth"
        with self.assertRaises(a.AuthError):
            await self.client.collect(2026)
        self.assertEqual(self.ids, [])
    async def test_http(self):
        self.mode = "http"
        with self.assertRaises(a.PortalError):
            await self.client.collect(2026)
    async def test_redirect(self):
        self.mode = "redirect"
        with self.assertRaises(a.PortalError):
            await self.client.collect(2026)
    async def test_unknown(self):
        self.mode = "unknown"
        with self.assertRaises(a.FormatError):
            await self.client.collect(2026)
