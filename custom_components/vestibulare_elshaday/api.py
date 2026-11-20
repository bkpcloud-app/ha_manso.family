"""Read-only portal client; independent of Home Assistant."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from html import unescape
from urllib.parse import urlsplit
import aiohttp

UA = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
DISCIPLINAS = {1:"Arte", 21:"Ciências Físicas e Biológicas", 27:"Ed. Tecnológica", 12:"Educação Física", 65:"Escola da Inteligência", 30:"Ético Cristão", 6:"Geografia", 7:"História", 8:"Inglês", 42:"Língua Portuguesa", 10:"Matemática"}

DATE = re.compile(r"Aula\s+(\d{2}/\d{2}/\d{4})")
PROF = re.compile(r"─\s*<span\s+class=[\"']{2}\s*>(.*?)</span>", re.I | re.S)
DESC = re.compile(r"limite-linha-va-card[\"'][^>]*>\s*<span[^>]*>(.*?)</span>", re.I | re.S)
DUE = re.compile(r"<small[^>]*>\s*até\s+(.*?)</small>", re.I | re.S)
EMPTY = re.compile(r"nenhum\s+planejamento(?:\s+(?:encontrado|cadastrado|disponível|aberto))?|não\s+(?:há|existem)\s+planejamentos", re.I)
LOGIN = re.compile(r"<input\b[^>]*(?:type\s*=\s*[\"']password|name\s*=\s*[\"']senha)", re.I)

class PortalError(Exception):
    """Portal communication error."""

class AuthError(PortalError):
    """Credentials rejected or session expired."""

class FormatError(PortalError):
    """Unexpected portal response."""

def normalize_portal(value):
    """Restrict credential submission to HTTPS Vestibulare hosts."""
    try:
        url = urlsplit(value.strip())
        host = url.hostname or ""
        if (url.scheme != "https" or not host.endswith(".vestibulare.com.br")
                or url.username is not None or url.password is not None
                or url.port not in (None, 443) or url.query or url.fragment
                or url.path.rstrip("/") not in ("", "/va")):
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid portal URL") from exc
    return f"https://{host}/va"

def clean(value):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())

def parse_html(source, name):
    if LOGIN.search(source):
        raise AuthError("Sessão expirada")
    dates = list(DATE.finditer(source))
    if not dates:
        if EMPTY.search(clean(source)):
            return []
        raise FormatError(f"{name}: lista vazia não reconhecida")
    items = []
    for i, date in enumerate(dates):
        block = source[date.end():dates[i+1].start() if i+1 < len(dates) else len(source)]
        prof, desc, due = PROF.findall(block), DESC.findall(block), DUE.findall(block)
        if len(prof) != 1 or len(desc) != 1 or len(due) > 1:
            raise FormatError(f"{name}: estrutura ambígua")
        data = date.group(1)
        prazo = clean(due[0]) if due else ""
        try:
            datetime.strptime(data, "%d/%m/%Y")
            if prazo:
                datetime.strptime(prazo, "%d/%m/%Y %H:%M")
        except ValueError as exc:
            raise FormatError(f"{name}: data inválida") from exc
        items.append(dict(disciplina=name, data=data, professor=clean(prof[0]), descricao=clean(desc[0]), prazo=prazo))
    return items

def inspect_submission_markers(source, name):
    """Collect limited HTML evidence, never infer a student's submission from an icon.

    The VA planning endpoint is not an authenticated proof of delivery.
    This probe allows comparison of real card markers after deployment,
    without exposing full page HTML, cookies, credentials, or pupil data.
    """
    dates = list(DATE.finditer(source))
    result = []
    for i, date in enumerate(dates):
        block = source[date.end():dates[i + 1].start() if i + 1 < len(dates) else len(source)]
        markers = []
        for tag in re.findall(r"<(?:i|span|svg|div|a|button)\\b[^>]*>", block, re.I):
            for key, value in re.findall(r"""(class|title|aria-label|data-[a-z0-9_-]+)\\s*=\\s*["']([^"']{1,140})["']""", tag, re.I):
                cleaned = clean(value)[:100]
                if re.search(r"check|success|entreg|conclu|pend|status|finaliz|enviad|realiz|aprov", key + " " + cleaned, re.I):
                    marker = key.lower() + "=" + cleaned
                    if marker not in markers:
                        markers.append(marker)
        result.append({"disciplina": name, "aula": date.group(1),
                       "status_entrega": "nao_verificado",
                       "indicadores_html": markers[:8]})
    return result


class PortalClient:
    def __init__(self, session, username, password, base):
        self.session = session
        self.username = username
        self.password = password
        self.base = base
        self.last_diagnostics = []

    async def _request(self, method, path, **kwargs):
        try:
            async with self.session.request(method, self.base + path, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False, **kwargs) as response:
                if response.status in (401, 403):
                    raise AuthError("Acesso recusado pelo portal")
                if response.status != 200:
                    raise PortalError(f"HTTP {response.status}")
                return await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as exc:
            raise PortalError("Falha de comunicação com o portal") from exc

    async def login(self):
        self.session.cookie_jar.clear()
        body = await self._request("POST", "/ajax/verificaLogin.php?redirectVtb=&app=off", data={"login":self.username, "senha":self.password, "ipAcesso":""})
        try:
            status = json.loads(body)["status"]
        except (ValueError, TypeError, KeyError) as exc:
            raise PortalError("Resposta de autenticação não reconhecida") from exc
        if isinstance(status, bool) or str(status) != "0":
            raise AuthError("Login recusado pelo portal")

    async def collect(self, year):
        await self.login()
        result = []
        self.last_diagnostics = []
        for id_, name in DISCIPLINAS.items():
            body = await self._request("GET", "/pages/planejamento/ajax/planejamentos-lista.php", params={"idTurma":"", "anoSelecionado":str(year), "idUsuarioSelecionado":"", "idDisciplina":str(id_), "idPlanejamento":"", "idPeriodo":"", "order":"", "todasAsTurmas":"true", "ordenacaoPlanejamentos":"abertos"})
            result.extend(parse_html(body, name))
            self.last_diagnostics.extend(inspect_submission_markers(body, name))
        return result
