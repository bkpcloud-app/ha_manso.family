"""Read-only portal client; independent of Home Assistant."""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import PurePosixPath
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

# Diagnostics are metadata-only: never record HTML, student identifiers,
# cookie contents, credentials, query strings or school activity text.
_VISUAL_WORD = re.compile(
    r"check|tick|success|conclu|entreg|finaliz|pend|lido|status|realiz|"
    r"complet|aprov|verde|green|verified|feito|enviad", re.I
)
_VISUAL_ATTRS = {
    "class", "title", "alt", "aria-label", "data-status",
    "data-entregue", "data-concluido", "data-finalizado",
    "data-realizado", "data-completo", "style",
}
_VISUAL_TAGS = {"i", "svg", "img", "span", "a", "button", "div", "input", "use"}
_VISUAL_TOKEN = re.compile(r"[a-zA-Z0-9_#-]{2,60}")


class _VisualMarkers(HTMLParser):
    """Inspect status-looking tags without retaining private page data."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.markers = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VISUAL_TAGS or len(self.markers) >= 24:
            return
        details = []
        for key, value in attrs:
            if not isinstance(value, str):
                continue
            if key in _VISUAL_ATTRS:
                normalized = "".join(c for c in unicodedata.normalize(
                    "NFKD", value.lower()) if not unicodedata.combining(c))
                tokens = []
                # Detect explicit negations before examining individual words.
                # "não entregue" and "entregue" MUST remain distinct.
                for word, safe in (
                    (r"\b(?:nao|not|sem)[-_ ]+entreg", "nao_entregue"),
                    (r"\b(?:nao|not|sem)[-_ ]+(?:conclu|complet|finaliz)", "nao_concluida"),
                ):
                    if re.search(word, normalized):
                        tokens.append(safe)
                if not tokens:
                    for raw in _VISUAL_TOKEN.findall(normalized):
                        marker = _VISUAL_WORD.search(raw)
                        if marker:
                            # Never store arbitrary values or private identifiers.
                            safe = raw if raw in {
                                "va-card-lido-inferior", "va-card-nao-lido-inferior",
                                "va-plan-card-status", "fa-check-circle",
                                "fa-check", "text-success", "is-completed",
                                "completed", "concluido", "concluida", "entregue",
                                "pendente", "sucesso", "status-success",
                            } else marker.group(0).lower()
                            if safe not in tokens:
                                tokens.append(safe)
                if tokens:
                    details.append(f"{key}={','.join(tokens[:5])}")
            elif tag == "img" and key == "src":
                # A status icon's fixed filename is useful, but query strings
                # or arbitrary filenames could leak student identifiers.
                filename = PurePosixPath(value.split("?", 1)[0].split("#", 1)[0]).name
                if re.fullmatch(
                    r"(?:fa-)?(?:check|tick|success|verified|completed|concluido|"
                    r"entregue)(?:[-_][a-zA-Z0-9]{1,20})?\.(?:svg|png|webp)", filename, re.I
                ):
                    details.append("icon_file=status-icon")
        if details:
            self.markers.append(f"{tag}:" + ";".join(details[:5]))


def inspect_visual_markers(source):
    """Status-looking metadata only, not proof of activity submission."""
    parser = _VisualMarkers()
    parser.feed(source)
    parser.close()
    return parser.markers


def inspect_submission_markers(source, name):
    """Return card identities only. Page-level icons cannot identify delivery.

    The HTML response may contain multiple cards and wrapper tags between
    dates; correlating those fragments to one card would misattribute status.
    """
    return [{"disciplina": name, "aula": date.group(1),
             "status_entrega": "nao_verificado"}
            for date in DATE.finditer(source)]


class PortalClient:
    def __init__(self, session, username, password, base):
        self.session = session
        self.username = username
        self.password = password
        self.base = base
        self.last_diagnostics = []
        self.last_visual_diagnostics = []
        self.last_counts = {}

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
        self.last_visual_diagnostics = []
        self.last_counts = {}
        for id_, name in DISCIPLINAS.items():
            body = await self._request("GET", "/pages/planejamento/ajax/planejamentos-lista.php", params={"idTurma":"", "anoSelecionado":str(year), "idUsuarioSelecionado":"", "idDisciplina":str(id_), "idPlanejamento":"", "idPeriodo":"", "order":"", "todasAsTurmas":"true", "ordenacaoPlanejamentos":"abertos"})
            items = parse_html(body, name)
            result.extend(items)
            self.last_counts[name] = len(items)
            self.last_diagnostics.extend(inspect_submission_markers(body, name))
            # Page-level metadata, not attributed to individual cards.
            self.last_visual_diagnostics.append({
                "disciplina": name, "marcadores": inspect_visual_markers(body),
            })
        return result
