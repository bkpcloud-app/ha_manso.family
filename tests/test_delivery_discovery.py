"""Regression tests for read-only authenticated delivery discovery."""
import importlib.util
from pathlib import Path
import unittest
import aiohttp
from aiohttp import web

spec = importlib.util.spec_from_file_location(
    "va_api_delivery",
    Path(__file__).parents[1] / "custom_components/vestibulare_elshaday/api.py",
)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class MenuDiscovery(unittest.TestCase):
    def test_menu_and_safe_routes(self):
        html = (
            '<a href="/va/pages/mural/lista.php">Mural da Turma</a>'
            '<a href="/va/pages/entregas/lista.php">Entregas</a>'
            '<a href="/va/pages/atividade/lista.php?aluno=ALICE">Atividades</a>'
        )
        result = a.inspect_authenticated_navigation(html)
        self.assertEqual(result["categorias"], ["atividades", "entregas", "mural"])
        self.assertEqual(len(result["_candidate_paths"]), 2)
        self.assertNotIn("ALICE", str(result))

    def test_reject_credentials_ids_and_mutating_paths(self):
        for href in (
            "/va/pages/mural/lista.php?token=SECRET",
            "/va/pages/mural/Alice.php",
            "/va/pages/atividade/salvar.php",
            "/va/pages/entregas/enviar.php",
            "https://evil.example/va/pages/mural/lista.php",
            "//evil.example/va/pages/mural/lista.php",
            "javascript:alert(1)",
            "https://[broken",
        ):
            with self.subTest(href=href):
                self.assertIsNone(a._safe_discovery_path(href))

    def test_status_words_are_not_proof(self):
        counts = a.inspect_possible_delivery_terms(
            '<div>Entregue, recebida, pendente, concluída. '
            'Aluno PRIVATE_SECRET</div>'
        )
        self.assertEqual(counts["entregue"], 1)
        self.assertEqual(counts["recebido"], 1)
        self.assertEqual(counts["pendente"], 1)
        self.assertEqual(counts["concluido"], 1)
        self.assertNotIn("PRIVATE_SECRET", str(counts))


class HTTPDiscovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        app = web.Application()
        app.router.add_post("/va/ajax/verificaLogin.php", self.login)
        app.router.add_get("/va/pages/planejamento/ajax/planejamentos-lista.php", self.plans)
        app.router.add_get("/va/index.php", self.index)
        app.router.add_get("/va/pages/mural/lista.php", self.mural)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True))
        self.client = a.PortalClient(
            self.session, "test@example.invalid", "test-password",
            f"http://127.0.0.1:{port}/va")

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def login(self, request):
        self.requests.append(("POST", request.path))
        result = web.json_response({"status": 0})
        result.set_cookie("session", "test")
        return result

    async def plans(self, request):
        self.requests.append(("GET", request.path))
        self.assertEqual(request.cookies.get("session"), "test")
        return web.Response(text="<div>Nenhum planejamento encontrado</div>")

    async def index(self, request):
        self.requests.append(("GET", request.path))
        self.assertEqual(request.cookies.get("session"), "test")
        return web.Response(text=(
            '<a href="/va/pages/mural/lista.php">Mural da Turma</a>'
            '<a href="/va/pages/atividade/enviar.php">Enviar tarefa</a>'))

    async def mural(self, request):
        self.requests.append(("GET", request.path))
        return web.Response(text="<div>Recebida; pendente; entregue</div>")

    async def test_auth_discovery_is_read_only_and_bounded(self):
        self.assertEqual(await self.client.collect(2026), [])
        self.assertEqual(len(self.client.last_counts), 11)
        discovery = self.client.delivery_discovery
        self.assertEqual(discovery["estado"], "diagnostico")
        page = discovery["paginas"][0]
        self.assertEqual(page["origem"], "index")
        self.assertTrue(page["rota_mural"])
        self.assertEqual(page["indicadores_gerais"]["entregue"], 1)
        self.assertEqual(len(self.requests), 14)  # POST login, 11 plans, 2 GETs
        self.assertEqual(sum(method == "POST" for method, _ in self.requests), 1)
        self.assertFalse(any("enviar.php" in path for _, path in self.requests))
        self.assertNotIn("status_entrega", str(discovery))

    async def test_probe_is_cached_after_first_poll(self):
        await self.client.collect(2026)
        before = len(self.requests)
        await self.client.collect(2026)
        self.assertEqual(len(self.requests)-before, 12)  # POST + 11 GETs


if __name__ == "__main__":
    unittest.main()
