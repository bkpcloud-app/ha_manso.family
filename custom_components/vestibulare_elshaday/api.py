"""Read-only portal client; independent of Home Assistant."""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata
import time
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


# Read-only discovery of navigation categories, with fixed output vocabulary.
# Never retain any URL/path, argument, dynamic field name or script content.
_ACTION_CATEGORIES = (
    ("atividade", re.compile(r"atividade|atividades|taref|exercic", re.I)),
    ("entrega", re.compile(r"entreg|envi|submit|upload", re.I)),
    ("conclusao", re.compile(r"conclu|finaliz|realiz|complet", re.I)),
    ("anexo", re.compile(r"anexo|arquivo|document", re.I)),
    ("resposta", re.compile(r"respost", re.I)),
    ("planejamento", re.compile(r"planej", re.I)),
)
_NAVIGATION_SECTIONS = {"atividade", "atividades", "planejamento", "tarefas", "aluno", "alunos"}
_NAVIGATION_KINDS = {"ajax", "scripts", "js"}
_NAVIGATION_LIMIT = 8


def _category(value):
    if not isinstance(value, str):
        return None
    return next((name for name, pattern in _ACTION_CATEGORIES
                 if pattern.search(value)), None)


def _safe_endpoint(value):
    if not isinstance(value, str) or len(value) > 400:
        return None
    if value.startswith(("javascript:", "data:", "#", "//")):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.netloc and not (
            parsed.scheme == "https" and parsed.hostname
            and parsed.hostname.endswith(".vestibulare.com.br")
        ):
            return None
    except ValueError:
        return None
    parts = parsed.path.strip("/").split("/")
    if parts[:1] == ["va"]:
        parts = parts[1:]
    if len(parts) < 4 or parts[0] != "pages":
        return None
    if parts[1] not in _NAVIGATION_SECTIONS or parts[2] not in _NAVIGATION_KINDS:
        return None
    category = _category(parts[-1])
    if category is None or not parts[-1].endswith((".php", ".js")):
        return None
    return f"{parts[1]}:{parts[2]}:{category}"


class _PortalNavigationProbe(HTMLParser):
    """Bounded, category-only diagnostic, with no freeform strings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paths = set()
        self.handlers = set()
        self.form_fields = set()
        self.form_count = 0
        self.button_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.form_count = min(self.form_count + 1, 20)
        if tag == "button":
            self.button_count = min(self.button_count + 1, 20)
        if tag in ("a", "form", "script", "iframe", "button"):
            for attr in ("href", "action", "src", "data-url"):
                if path := _safe_endpoint(attrs.get(attr)):
                    self.paths.add(path)
        for attr in ("onclick", "onsubmit", "data-action"):
            value = attrs.get(attr)
            if isinstance(value, str):
                # Only the first function name is inspected. The rest,
                # including arguments, never enters the output.
                match = re.match(r"^\s*([a-zA-Z_$][a-zA-Z0-9_$]{0,60})\s*\(", value)
                if match and (category := _category(match.group(1))):
                    self.handlers.add(category)
        if tag in ("input", "select", "textarea"):
            if category := _category(attrs.get("name")):
                self.form_fields.add(category)

    def snapshot(self):
        return {
            "caminhos": sorted(self.paths)[:_NAVIGATION_LIMIT],
            "acoes": sorted(self.handlers)[:_NAVIGATION_LIMIT],
            "campos": sorted(self.form_fields)[:_NAVIGATION_LIMIT],
            "formularios": self.form_count,
            "botoes": self.button_count,
        }


def inspect_portal_navigation(source):
    """Read-only parser: emit bounded categories, never identifying values."""
    parser = _PortalNavigationProbe()
    parser.feed(source)
    parser.close()
    return parser.snapshot()


def inspect_submission_markers(source, name):
    """Return card identities only. Page-level icons cannot identify delivery.

    The HTML response may contain multiple cards and wrapper tags between
    dates; correlating those fragments to one card would misattribute status.
    """
    return [{"disciplina": name, "aula": date.group(1),
             "status_entrega": "nao_verificado"}
            for date in DATE.finditer(source)]


# Navigation evidence only. User/student data and raw URLs are never emitted.
_DISCOVERY_WORDS = {
    "mural": re.compile(r"\bmural\b", re.I),
    "atividades": re.compile(r"\b(?:atividade|atividades|tarefa|tarefas)\b", re.I),
    "entregas": re.compile(r"\b(?:entrega|entregas|enviados|enviadas)\b", re.I),
}
_DISCOVERY_ROUTE = re.compile(
    r"^/(?:va/)?pages/(mural|atividade|atividades|tarefa|tarefas|entrega|entregas)"
    r"/(?:[a-z_-]{2,35}/)?[a-z_-]{2,55}\.php$", re.I
)
_DISCOVERY_DENY = re.compile(
    r"salvar|excluir|apagar|remover|delete|editar|alterar|registrar|"
    r"enviar|submit|upload|logout|sair", re.I
)


def _fold_menu(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))


def _safe_discovery_path(href):
    if not isinstance(href, str) or len(href) > 200 or href.startswith("//"):
        return None
    try:
        u = urlsplit(href)
    except ValueError:
        return None
    if (u.netloc or u.scheme or u.query or u.fragment
            or not _DISCOVERY_ROUTE.fullmatch(u.path)
            or _DISCOVERY_DENY.search(u.path)):
        return None
    return u.path


class _MenuEvidence(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.categories = set()
        self.routes = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.anchor = [_safe_discovery_path(dict(attrs).get("href")), ""]

    def handle_data(self, value):
        if self.anchor is not None and len(self.anchor[1]) < 150:
            self.anchor[1] += value[:150]

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            path, label = self.anchor
            folded = _fold_menu(label)
            category = next((name for name, regex in _DISCOVERY_WORDS.items()
                             if regex.search(folded)), None)
            if category:
                self.categories.add(category)
                if path and len(self.routes) < 8:
                    self.routes.append((category, path))
            self.anchor = None


def inspect_authenticated_navigation(source):
    """Report bounded categories; exact safe paths remain internal only."""
    p = _MenuEvidence()
    p.feed(source[:200000])
    p.close()
    folded = _fold_menu(source[:80000])
    return {
        "categorias": sorted(p.categories),
        "mencoes_html": sorted(name for name, regex in _DISCOVERY_WORDS.items()
                                if regex.search(folded)),
        "_candidate_paths": p.routes,
    }


def inspect_possible_delivery_terms(source):
    """Page-level hints, never proof that a specific assignment was sent."""
    body = _fold_menu(re.sub(r"<[^>]+>", " ", source[:100000]))
    return {name: min(len(re.findall(pattern, body)), 20) for name, pattern in {
        "enviado": r"\b(?:enviado|enviada|enviados|enviadas)\b",
        "entregue": r"\b(?:entregue|entregues)\b",
        "pendente": r"\b(?:pendente|pendentes)\b",
        "recebido": r"\b(?:recebido|recebida)\b",
        "concluido": r"\b(?:concluido|concluida)\b",
    }.items()}


class PortalClient:
    def __init__(self, session, username, password, base):
        self.session = session
        self.username = username
        self.password = password
        self.base = base
        self.last_diagnostics = []
        self.last_visual_diagnostics = []
        self.last_navigation_diagnostics = []
        self.last_counts = {}
        self.delivery_discovery = {"estado": "nao_executado"}
        self._next_discovery = 0.0

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


    async def discover_navigation(self):
        """Bounded, read-only inspection of authenticated home and mural."""
        diagnostics = []
        for home in ("/index.php", "/"):
            label = "index" if home == "/index.php" else "raiz"
            try:
                page = await asyncio.wait_for(self._request("GET", home), timeout=6)
            except (PortalError, asyncio.TimeoutError):
                diagnostics.append({"origem": label, "estado": "indisponivel"})
                continue
            if LOGIN.search(page):
                diagnostics.append({"origem": label, "estado": "pagina_login"})
                continue
            nav = inspect_authenticated_navigation(page)
            report = {"origem": label, "estado": "consultada",
                      "categorias": nav["categorias"],
                      "mencoes_html": nav["mencoes_html"],
                      "rota_mural": False}
            # Only GET navigational pages explicitly linked in the real menu;
            # no guessed endpoint, query string, form action or submission.
            candidate = next((route for category, route in nav["_candidate_paths"]
                              if category in ("mural", "entregas")), None)
            if candidate is not None:
                route = candidate[3:] if candidate.startswith("/va/") else candidate
                try:
                    mural = await asyncio.wait_for(
                        self._request("GET", route), timeout=6)
                except (PortalError, asyncio.TimeoutError):
                    report["mural_estado"] = "indisponivel"
                else:
                    report["rota_mural"] = True
                    report["mural_estado"] = "consultada"
                    report["indicadores_gerais"] = inspect_possible_delivery_terms(mural)
                    # Do not infer submission of an individual activity.
            diagnostics.append(report)
            if nav["categorias"] or nav["mencoes_html"]:
                break
        return {"estado": "diagnostico", "paginas": diagnostics[:2]}

    async def collect(self, year):
        await self.login()
        result = []
        self.last_diagnostics = []
        self.last_visual_diagnostics = []
        self.last_navigation_diagnostics = []
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
            if name in ("Arte", "Língua Portuguesa"):
                self.last_navigation_diagnostics.append({
                    "disciplina": name,
                    "estrutura": inspect_portal_navigation(body),
                })
        # Additional authenticated GET discovery is isolated from normal
        # polling and cached for six hours. Failures do not erase activities.
        if time.monotonic() >= self._next_discovery:
            self._next_discovery = time.monotonic() + 21600
            try:
                self.delivery_discovery = await asyncio.wait_for(
                    self.discover_navigation(), timeout=14)
            except (PortalError, asyncio.TimeoutError, ValueError):
                self.delivery_discovery = {"estado": "indisponivel"}
        return result
