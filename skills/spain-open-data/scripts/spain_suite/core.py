"""Bounded, read-only access to Spain's official public data. Python 3.11+."""
from __future__ import annotations

import copy
import datetime as dt
import difflib
import hashlib
import json
import math
import ssl
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable
from zoneinfo import ZoneInfo

VERSION = "0.4.0"
MADRID = ZoneInfo("Europe/Madrid")
BOE = "https://www.boe.es"
BDNS = "https://www.infosubvenciones.es/bdnstrans/api"
INE = "https://servicios.ine.es/wstempus/js/ES"
DATOS = "https://datos.gob.es/apidata/catalog/dataset"
CATASTRO = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero"
PLACSP = "https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom"
ALLOWED_HOSTS = frozenset({"www.boe.es", "boe.es", "www.infosubvenciones.es", "servicios.ine.es", "datos.gob.es", "ovc.catastro.meh.es", "contrataciondelestado.es"})
SOURCE_NOTICE = "Independent software by Sami Halawa; not an official government service. Verify consequential decisions in the official source."
MAX_BYTES = 8 * 1024 * 1024

class SourceError(Exception):
    """Expected provider or input failure, safe to return to a client."""
    def __init__(self, code: str, message: str, source_url: str | None = None):
        super().__init__(message)
        self.code, self.source_url = code, source_url


def fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def text_input(value: str, name: str, maximum: int = 200, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise SourceError("invalid_input", f"{name} must be a {'nonempty ' if not empty else ''}string of at most {maximum} characters.")
    if any(ord(c) < 32 for c in value):
        raise SourceError("invalid_input", f"{name} must not contain control characters.")
    return value.strip()


def integer(value: int, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SourceError("invalid_input", f"{name} must be an integer between {low} and {high}.")
    return value


def date_input(value: str = "") -> dt.date:
    if value == "":
        return dt.datetime.now(MADRID).date()
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SourceError("invalid_input", "Date must be a valid YYYY-MM-DD calendar date.") from exc


def safe_url(url: str) -> str:
    if not isinstance(url,str) or len(url)>8192 or any(ord(c)<32 for c in url):
        raise SourceError("blocked_url","Invalid source URL.")
    try:
        p=urllib.parse.urlsplit(url)
        invalid=(p.scheme!="https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password or p.port not in (None,443) or p.fragment)
    except ValueError:
        invalid=True
    if invalid:
        raise SourceError("blocked_url","Only HTTPS requests to the configured official-source allowlist are permitted.")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _CredentialFreeProxy(urllib.request.ProxyHandler):
    """Keep system proxy routing, but never use ambient proxy credentials."""
    def proxy_open(self, req, proxy, type):
        # A bypassed proxy is unused. Defer validation until a live request so
        # offline commands still work in environments with authenticated proxies.
        if req.host and urllib.request.proxy_bypass(req.host):
            return None
        # urllib accepts authority-only proxies and userinfo containing slashes.
        # Reject the delimiter before its permissive parser can add auth headers.
        if "@" in proxy:
            raise SourceError("proxy_credentials_blocked", "Authenticated proxy URLs are not supported; no connection was made.")
        try:
            return super().proxy_open(req, proxy, type)
        except ValueError:
            raise SourceError("invalid_proxy", "The configured proxy URL is invalid.") from None


@dataclass(frozen=True)
class Fetch:
    body: bytes
    url: str
    fetched_at: str
    content_type: str
    cached: bool = False
    complete: bool = True

    def provenance(self) -> dict[str, Any]:
        record = {"url": self.url, "retrieved_at": self.fetched_at, "sha256": hashlib.sha256(self.body).hexdigest(), "cache_hit": self.cached}
        if not self.complete:
            record.update(complete=False, sha256_scope="response_prefix", bytes_retained=len(self.body), byte_limit=MAX_BYTES)
        return record

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceError("invalid_response", "The source did not return valid JSON.", self.url) from exc

    def xml(self) -> ET.Element:
        # Reject DTD/entity declarations before using the standard-library XML parser.
        if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", self.body.replace(b"\x00", b""), re.I):
            raise SourceError("unsafe_xml", "DTD/entity declarations are not accepted.", self.url)
        if not self.complete:
            return _atom_prefix(self.body, self.url)
        try:
            return ET.fromstring(self.body)
        except ET.ParseError as exc:
            raise SourceError("invalid_response", "The source did not return valid XML.", self.url) from exc


def _atom_prefix(body: bytes, url: str) -> ET.Element:
    """Retain only completed direct children; never claim a clipped document is complete."""
    _feed_url(url)
    parser = ET.XMLPullParser(events=("start", "end"))
    root = None
    depth = 0
    try:
        parser.feed(body)
        for event, node in parser.read_events():
            if event == "start":
                depth += 1
                if depth == 1:
                    if node.tag != "{http://www.w3.org/2005/Atom}feed":
                        raise SourceError("schema_changed", "Expected an official Atom feed.", url)
                    root = ET.Element(node.tag, node.attrib)
            else:
                if depth == 2 and root is not None:
                    root.append(node)
                depth -= 1
        # Do not close the parser: EOF is deliberately not asserted for a prefix.
    except ET.ParseError as exc:
        raise SourceError("invalid_response", "The retained Atom prefix contains malformed XML.", url) from exc
    if root is None or not any(node.tag == "{http://www.w3.org/2005/Atom}entry" for node in root):
        raise SourceError("response_too_large", "No complete Atom entry fits inside the bounded response window (at most 8 MiB); no tender results were inferred.", url)
    return root


class OfficialClient:
    """TLS-verified, bounded reads; no cookies, credentials, analytics or disk cache."""
    def __init__(self, ttl: int = 300, max_cache_bytes: int = 32 * 1024 * 1024):
        self.ttl, self.max_cache_bytes = ttl, max_cache_bytes
        self.cache: OrderedDict[str, tuple[float, Fetch]] = OrderedDict()
        self.lock = threading.Lock()
        self.last_request: dict[str, float] = {}
        self.opener = urllib.request.build_opener(_CredentialFreeProxy(), _SafeRedirect())

    def get(self, url: str, params: dict[str, Any] | None = None, accept: str = "application/json", *, allow_atom_prefix: bool = False) -> Fetch:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        safe_url(url)
        if allow_atom_prefix:
            _feed_url(url)
            if accept != "application/atom+xml":
                raise SourceError("invalid_input", "Bounded prefixes are supported only for the official PLACSP Atom feed.")
        key = accept + " " + url + (" prefix" if allow_atom_prefix else "")
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < self.ttl:
                f = cached[1]
                return Fetch(f.body, f.url, f.fetched_at, f.content_type, True, complete=f.complete)
            host = urllib.parse.urlsplit(url).hostname or ""
            wait = max(0.0, self.last_request.get(host, 0.0) + .25 - time.monotonic())
            self.last_request[host] = time.monotonic() + wait
        if wait:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": f"SpainAssistantSuite/{VERSION} (+https://samihalawa.com)", "Accept": accept, "Accept-Encoding": "identity"})
        for attempt in range(2):
            try:
                with self.opener.open(req, timeout=20) as response:
                    safe_url(response.geturl())
                    chunks, total, complete = [], 0, True
                    # PLACSP pages are large: use a smaller latency-bounded window
                    # for interactive reads, under the unchanged global 8 MiB cap.
                    read_limit = min(MAX_BYTES, 1024 * 1024) if allow_atom_prefix else MAX_BYTES
                    while True:
                        # One lookahead byte detects overflow; retained/parsing bytes stay capped.
                        part = response.read(min(65536, read_limit - total + 1))
                        if not part:
                            break
                        total += len(part)
                        if total > read_limit:
                            if not allow_atom_prefix:
                                raise SourceError("response_too_large", "Official response exceeds the 8 MiB safety limit; narrow the query.", url)
                            chunks.append(part[:len(part) - (total - read_limit)])
                            complete = False
                            break
                        chunks.append(part)
                    f = Fetch(b"".join(chunks), response.geturl(), dt.datetime.now(dt.timezone.utc).isoformat(), response.headers.get("Content-Type", ""), complete=complete)
                with self.lock:
                    self.cache[key] = (time.monotonic(), f)
                    self.cache.move_to_end(key)
                    while len(self.cache) > 64 or sum(len(v[1].body) for v in self.cache.values()) > self.max_cache_bytes:
                        self.cache.popitem(last=False)
                return f
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt == 0:
                    retry = exc.headers.get("Retry-After", "1")
                    # Never ignore a longer provider backoff by retrying too early.
                    if retry.isdigit() and int(retry) <= 3:
                        time.sleep(max(1, int(retry)))
                        continue
                code = "source_not_found" if exc.code == 404 else "source_rate_limited" if exc.code == 429 else "source_http_error"
                raise SourceError(code, f"Official source returned HTTP {exc.code}; this is not evidence of no results.", url) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if isinstance(exc, ssl.SSLError) or isinstance(getattr(exc, "reason", None), ssl.SSLError):
                    raise SourceError("source_tls_error", "TLS certificate verification failed in this Python runtime. Check its trusted CA certificates; verification was not disabled.", url) from exc
                raise SourceError("source_unavailable", "The official source could not be reached; no result was inferred.", url) from exc
        raise SourceError("source_unavailable", "Official source did not respond.", url)

CLIENT = OfficialClient()


def envelope(data: Any, sources: list[Fetch], warnings: list[str] | None = None, **coverage: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "sources": [s.provenance() for s in sources], "coverage": coverage, "warnings": warnings or [], "notice": SOURCE_NOTICE}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def inner_text(element: ET.Element | None) -> str:
    return " ".join(" ".join(element.itertext()).split()) if element is not None else ""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def descendants(element: ET.Element, tag: str) -> list[ET.Element]:
    return [e for e in element.iter() if local_name(e.tag) == tag]


def first_text(element: ET.Element, tag: str) -> str | None:
    found = descendants(element, tag)
    return inner_text(found[0]) if found else None


def path_text(element: ET.Element, *tags: str) -> str | None:
    current = [element]
    for tag in tags:
        current = [c for p in current for c in p if local_name(c.tag) == tag]
    return inner_text(current[0]) if current else None


def bulletin_items(value: Any, context: dict[str, Any] | None = None):
    context = context or {}
    if isinstance(value, list):
        for item in value:
            yield from bulletin_items(item, context)
    elif isinstance(value, dict):
        ctx = dict(context)
        if "nombre" in value:
            ctx["section_or_body"] = value["nombre"]
        if "identificador" in value and "titulo" in value:
            yield {**value, "context": ctx}
        else:
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from bulletin_items(child, ctx)


def link_value(value: Any) -> str | None:
    return value.get("texto") if isinstance(value, dict) else value if isinstance(value, str) else None


def deadline_assessment(start: Any = None, end: Any = None, as_of: str = "") -> dict[str, Any]:
    """Date-only triage, never a legal open/closed or eligibility determination."""
    today=date_input(as_of)
    def parse(v):
        try:
            return dt.date.fromisoformat(v[:10]) if isinstance(v,str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T| )",v) else None
        except ValueError:
            return None
    a,b=parse(start),parse(end)
    if a and b and a>b: state="conflicting_dates"
    elif start not in (None,"") and a is None or end not in (None,"") and b is None: state="unrecognized_date"
    elif a and today<a: state="not_started_by_date"
    elif b and today>b: state="past_end_date"
    elif b and today==b: state="ends_today_check_time"
    elif b and a and a<=today<b: state="within_published_dates"
    elif b and today<b: state="end_date_ahead_start_unverified"
    else: state="deadline_not_established"
    return {"as_of":today.isoformat(),"date_state":state,"start_date":start,"end_date":end,"eligibility_verified":False,"portal_status_verified":False}


def _bulletin_data(f: Fetch) -> dict[str, Any]:
    body=f.json()
    if not isinstance(body,dict) or not isinstance(body.get("status"),dict):
        raise SourceError("schema_changed","Missing official bulletin response status.",f.url)
    code=str(body["status"].get("code",""))
    if code!="200":
        raise SourceError("source_not_found" if code=="404" else "source_reported_error","The bulletin service did not return a successful issue.",f.url)
    data=body.get("data");summary=data.get("sumario") if isinstance(data,dict) else None
    if not isinstance(summary,dict) or not isinstance(summary.get("diario"),(list,dict)):
        raise SourceError("schema_changed","Missing official issue structure; no empty result was inferred.",f.url)
    return data


def _feed_url(url: str) -> str:
    safe_url(url);p=urllib.parse.urlsplit(url)
    if p.hostname!="contrataciondelestado.es" or p.query or not re.fullmatch(r"/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3(?:_[0-9_]+)?\.atom",p.path):
        raise SourceError("invalid_input","Use a continuation URL returned by this PLACSP feed.")
    return url


def licita_search(query: str = "", cpv_prefix: str = "", max_pages: int = 1, limit: int = 20, cursor: str = "", offset: int = 0, deadline_from: str = "") -> dict[str, Any]:
    """Search a bounded PLACSP window. Oversized pages expose complete prefix entries with explicit partial coverage; continuation never skips an unread suffix. Optional deadline_from filters dates, not legal application status."""
    query=text_input(query,"query");cpv_prefix=text_input(cpv_prefix,"cpv_prefix",8)
    if cpv_prefix and not re.fullmatch(r"\d{2,8}",cpv_prefix):raise SourceError("invalid_input","cpv_prefix must contain 2–8 digits.")
    integer(max_pages,"max_pages",1,3);integer(limit,"limit",1,50);integer(offset,"offset",0,100000)
    threshold=date_input(deadline_from) if deadline_from else None
    url=_feed_url(cursor or PLACSP);rows=[];sources=[];seen=set();deleted=set();visited=set();scanned=0;unknown_deadlines=0;errors=[]
    next_url=None;next_offset=None;stopped=False;offset_on_page=offset
    prefix_pages=[];older_page_cursor=None;continuation_blocked_reason=None
    for _ in range(max_pages):
        if url in visited:raise SourceError("schema_changed","The source returned a cyclic continuation link.",url)
        visited.add(url)
        try:
            f=CLIENT.get(_feed_url(url),accept="application/atom+xml",allow_atom_prefix=True);root=f.xml()
            if root.tag!="{http://www.w3.org/2005/Atom}feed":raise SourceError("schema_changed","Expected an official Atom feed.",f.url)
        except SourceError as exc:
            if not sources:
                if exc.code == "response_too_large":
                    raise SourceError("response_too_large", "The official PLACSP Atom page exceeds the 8 MiB read limit. Query, limit and max_pages filter after retrieval and cannot reduce this upstream page. No tender results were inferred.", exc.source_url) from exc
                raise
            errors.append({"code":exc.code,"message":str(exc),"source_url":exc.source_url});next_url=url;next_offset=offset_on_page;break
        sources.append(f)
        if not f.complete:
            prefix_pages.append(f.url)
            errors.append({"code":"response_prefix_only","message":f"Only complete entries within the retained {len(f.body)}-byte prefix were parsed. The page suffix, later entries and tombstones were not examined.","source_url":f.url})
        deleted.update(e.attrib.get("ref","") for e in descendants(root,"deleted-entry"))
        entries=[e for e in root if local_name(e.tag)=="entry"]
        if offset_on_page>len(entries):raise SourceError("invalid_input","Offset exceeds this feed page; start again because the live feed may have changed.",f.url)
        for index in range(offset_on_page,len(entries)):
            entry=entries[index];eid=path_text(entry,"id")
            if not eid or eid in seen or eid in deleted:continue
            scanned+=1;title=path_text(entry,"title") or "";cpvs=list(dict.fromkeys(inner_text(e) for e in descendants(entry,"ItemClassificationCode")))
            if query and not all(t in fold(inner_text(entry)) for t in fold(query).split()):continue
            if cpv_prefix and not any(c.startswith(cpv_prefix) for c in cpvs):continue
            status_nodes=descendants(entry,"ContractFolderStatus");status=status_nodes[0] if status_nodes else entry
            deadlines=descendants(status,"TenderSubmissionDeadlinePeriod");end=first_text(deadlines[0],"EndDate") if deadlines else None
            assessment=deadline_assessment(end=end)
            if threshold:
                try:parsed=dt.date.fromisoformat(end or "")
                except (ValueError,TypeError):unknown_deadlines+=1;continue
                if parsed<threshold:continue
            if len(rows)>=limit:
                next_url=url;next_offset=index;stopped=True;break
            seen.add(eid)
            project=descendants(status,"ProcurementProject");budget=descendants(project[0],"BudgetAmount") if project else []
            parties=descendants(status,"LocatedContractingParty");docs=[]
            for ref in descendants(status,"DocumentReference")+descendants(status,"LegalDocumentReference")+descendants(status,"TechnicalDocumentReference"):
                docs.extend(inner_text(u) for u in descendants(ref,"URI") if inner_text(u).startswith(("https://","http://")))
            hrefs=[e.attrib.get("href") for e in entry if local_name(e.tag)=="link" and e.attrib.get("rel","alternate")=="alternate"]
            rows.append({"id":eid,"title":title,"official_url":hrefs[0] if hrefs else eid,"updated":path_text(entry,"updated"),"reference":first_text(status,"ContractFolderID"),"status_code":first_text(status,"ContractFolderStatusCode"),"authority":first_text(parties[0],"Name") if parties else None,"cpv":cpvs,"budget_excluding_tax":first_text(budget[0],"TaxExclusiveAmount") if budget else None,"currency":next((e.attrib.get("currencyID") for e in budget[0] if local_name(e.tag)=="TaxExclusiveAmount"),None) if budget else None,"deadline_date":end,"deadline_time":first_text(deadlines[0],"EndTime") if deadlines else None,"deadline_assessment":assessment,"document_urls":list(dict.fromkeys(docs))})
        if stopped:break
        if not f.complete:
            candidate=next((e.attrib.get("href") for e in root if local_name(e.tag)=="link" and e.attrib.get("rel")=="next"),None)
            older_page_cursor=_feed_url(candidate) if candidate else None
            # Advancing to an older page would silently skip the unread suffix.
            next_url=None;next_offset=None;continuation_blocked_reason="unread_page_suffix"
            break
        next_url=next((e.attrib.get("href") for e in root if local_name(e.tag)=="link" and e.attrib.get("rel")=="next"),None)
        next_offset=0 if next_url else None
        if not next_url:break
        url=_feed_url(next_url);offset_on_page=0
    rows=[r for r in rows if r['id'] not in deleted]
    warnings=["Bounded feed window, not all Spanish tenders. A future deadline does not establish an open procedure; verify status, lots, amendments and the official profile.","Continuation preserves within-page matches. Live feed pages can change; deduplicate stable tender IDs across calls."]
    if prefix_pages:
        warnings.append("Partial source: only complete entries inside a bounded response prefix (at most 1 MiB for interactive reads, below the 8 MiB hard limit) were checked. Entries and cancellation tombstones outside it remain unexamined. A prefix SHA-256 does not identify the complete feed. Verify each contracting profile.")
    if continuation_blocked_reason:
        warnings.append("Lossless continuation is blocked at the unread page suffix. The separately reported older_page_cursor is an optional older window, not continuation past all entries in this page.")
    if threshold:warnings.append("deadline_from excludes missing/unparseable deadlines; these exclusions are counted separately.")
    next_args={"query":query,"cpv_prefix":cpv_prefix,"max_pages":max_pages,"limit":limit,"cursor":next_url,"offset":next_offset,"deadline_from":deadline_from} if next_url else None
    result=envelope(rows,sources,warnings,pages_fetched=len(sources),entries_examined=scanned,returned=len(rows),result_limit_reached=stopped,next_cursor=next_url,next_offset=next_offset,next_request=next_args,unknown_deadlines_excluded=unknown_deadlines,deleted_ids_observed=len(deleted),partial=bool(errors),exhaustive=False,prefix_pages=prefix_pages,older_page_cursor=older_page_cursor,continuation_blocked_reason=continuation_blocked_reason)
    if errors:
        result["errors"]=errors
        if any(error["code"] != "response_prefix_only" for error in errors):
            result["warnings"].append("A later feed page could not be read. Earlier results are preserved; do not claim that the complete requested window was checked.")
    return result


def ayudas_search(query: str, page: int = 0, page_size: int = 10) -> dict[str, Any]:
    """Search official BDNS call descriptions with explicit pagination. A result is not proof that a call is open, competitive or suitable."""
    query = text_input(query, "query", 160, False)
    integer(page, "page", 0, 10000); integer(page_size, "page_size", 1, 50)
    f = CLIENT.get(BDNS + "/convocatorias/busqueda", {"vpd": "GE", "page": page, "pageSize": page_size, "descripcion": query})
    body = f.json()
    if not isinstance(body, dict) or not isinstance(body.get("content"), list):
        raise SourceError("schema_changed", "BDNS search response does not match the expected content list.", f.url)
    rows = []
    for r in body["content"]:
        number = str(r.get("numeroConvocatoria", ""))
        rows.append({"bdns_number": number, "internal_id": r.get("id"), "title": r.get("descripcion"), "received_date": r.get("fechaRecepcion"), "administration": [r.get(x) for x in ("nivel1", "nivel2", "nivel3") if r.get(x)], "official_url": f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{number}", "application_status": "not_verified"})
    warnings = ["Search results include historical calls and direct/nominative awards. Read each call and its legal bases to establish who may apply and whether a deadline remains open."]
    if body.get("advertencia"):
        warnings.append(body["advertencia"])
    return envelope(rows, [f], warnings, page=page, page_size=page_size, total=body.get("totalElements"), next_page=None if body.get("last") else page + 1)


def ayudas_call(bdns_number: str) -> dict[str, Any]:
    """Retrieve the official BDNS call record by its public number, not its internal search ID. Preserve eligibility and deadline fields as published."""
    if not isinstance(bdns_number, str) or not re.fullmatch(r"\d{1,10}", bdns_number):
        raise SourceError("invalid_input", "bdns_number must be the public numeric BDNS call number.")
    f = CLIENT.get(BDNS + "/convocatorias", {"numConv": bdns_number})
    body = f.json()
    if not isinstance(body, dict) or str(body.get("codigoBDNS", "")) != bdns_number:
        raise SourceError("schema_changed", "BDNS did not return a call object.", f.url)
    return envelope(body, [f], ["This is a published call record, not an eligibility determination. Official bases, amendments and the application portal take precedence. A direct award is not an open application opportunity."], bdns_number=bdns_number)


def boe_daily(date: str, query: str = "", limit: int = 30) -> dict[str, Any]:
    """Read a specific BOE issue and filter item titles. Returns official identifiers and links, not an exhaustive search of legislation."""
    d = date_input(date); query = text_input(query, "query"); integer(limit, "limit", 1, 100)
    f = CLIENT.get(f"{BOE}/datosabiertos/api/boe/sumario/{d:%Y%m%d}")
    body = _bulletin_data(f)
    items = list(bulletin_items(body))
    found = [r for r in items if all(t in fold(r.get("titulo", "")) for t in fold(query).split())]
    rows = [{"id": r["identificador"], "title": r["titulo"], "html_url": r.get("url_html"), "xml_url": r.get("url_xml"), "pdf_url": link_value(r.get("url_pdf")), "context": r["context"]} for r in found[:limit]]
    return envelope(rows, [f], ["Title matching only, within this issue. Publication date is not necessarily entry-into-force date."], date=d.isoformat(), matching_items=len(found), returned=len(rows), truncated=len(found)>limit)


def _boe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"BOE-[AB]-\d{4}-\d{1,8}", value):
        raise SourceError("invalid_input", "Use an official BOE identifier, for example BOE-A-2017-12902.")
    return value


def boe_document(document_id: str, max_chars: int = 40000) -> dict[str, Any]:
    """Read the published BOE document XML and return text with provenance. Output truncation is explicit."""
    _boe_id(document_id); integer(max_chars, "max_chars", 1000, 100000)
    f = CLIENT.get(f"{BOE}/diario_boe/xml.php", {"id": document_id}, accept="application/xml")
    root = f.xml()
    blocks = root.find("texto")
    text = "\n".join(inner_text(e) for e in blocks) if blocks is not None else ""
    if not text:
        raise SourceError("no_text", "The official XML contains no text body.", f.url)
    return envelope({"id": document_id, "title": root.findtext("metadatos/titulo"), "publication_date": root.findtext("metadatos/fecha_publicacion"), "text": text[:max_chars], "official_url": f"{BOE}/diario_boe/txt.php?id={document_id}"}, [f], ["Published wording is not automatically the current consolidated wording. Check amendments and transitional provisions."], characters=len(text), returned_characters=min(len(text),max_chars), truncated=len(text)>max_chars)


def _law(law_id: str) -> tuple[Fetch, list[ET.Element]]:
    _boe_id(law_id)
    f = CLIENT.get(f"{BOE}/datosabiertos/api/legislacion-consolidada/id/{law_id}/texto", accept="application/xml")
    blocks = f.xml().findall(".//bloque")
    if not blocks:
        raise SourceError("schema_changed", "No consolidated text blocks were returned.", f.url)
    return f, blocks


def _version(block: ET.Element, as_of: dt.date) -> ET.Element | None:
    cutoff = as_of.strftime("%Y%m%d")
    candidates = [v for v in block.findall("version") if v.get("fecha_vigencia", v.get("fecha_publicacion", "99999999")) <= cutoff]
    return max(candidates, key=lambda v: (v.get("fecha_vigencia", v.get("fecha_publicacion", "")), v.get("fecha_publicacion", ""))) if candidates else None


def boe_consolidated(law_id: str, block_id: str = "", as_of: str = "", offset: int = 0, limit: int = 10) -> dict[str, Any]:
    """Read dated consolidated law blocks. Use returned block IDs for article-level retrieval; selection follows source version dates, not legal advice."""
    d = date_input(as_of); block_id = text_input(block_id, "block_id", 100)
    integer(offset, "offset", 0, 10000); integer(limit, "limit", 1, 30)
    f, blocks = _law(law_id)
    if block_id:
        blocks = [b for b in blocks if b.get("id") == block_id]
        if not blocks:
            raise SourceError("block_not_found", "The requested article/block ID is not in this law.", f.url)
    rows = []
    for b in blocks[offset:offset+limit]:
        v = _version(b, d)
        content = inner_text(v) if v is not None else None
        rows.append({"block_id": b.get("id"), "title": b.get("titulo"), "type": b.get("tipo"), "selected_version": dict(v.attrib) if v is not None else None, "text": content[:60000] if content else content, "text_truncated": bool(content and len(content)>60000), "available_versions": [dict(v.attrib) for v in b.findall("version")]})
    return envelope(rows, [f], ["BOE consolidated legislation is informative, not legally authoritative. The selected version follows published version dates; this does not resolve transitional provisions, retroactivity or jurisdiction-specific applicability."], as_of=d.isoformat(), total_blocks=len(blocks), offset=offset, next_offset=offset+limit if offset+limit<len(blocks) else None)


def boe_compare(law_id: str, block_id: str, older_date: str, newer_date: str) -> dict[str, Any]:
    """Compare one consolidated law block at two explicit dates. Returns a reproducible text diff and both version metadata."""
    old, new = date_input(older_date), date_input(newer_date)
    if not older_date or not newer_date or old > new:
        raise SourceError("invalid_input", "Provide two explicit dates with older_date no later than newer_date.")
    block_id = text_input(block_id, "block_id", 100, False)
    f, blocks = _law(law_id)
    block = next((b for b in blocks if b.get("id") == block_id), None)
    if block is None:
        raise SourceError("block_not_found", "The requested block ID does not exist in this law.", f.url)
    a,b = _version(block,old),_version(block,new)
    if a is None or b is None:
        raise SourceError("version_unavailable", "The source has no version for one of the requested dates; no text was invented.",f.url)
    ta = [inner_text(e) for e in a]; tb = [inner_text(e) for e in b]
    diff = "\n".join(difflib.unified_diff(ta,tb,fromfile=older_date,tofile=newer_date,lineterm=""))
    return envelope({"law_id":law_id,"block_id":block_id,"older_version":dict(a.attrib),"newer_version":dict(b.attrib),"changed":ta!=tb,"older_date":older_date,"newer_date":newer_date,"older_text":"\n".join(ta)[:60000],"newer_text":"\n".join(tb)[:60000],"text_truncated":len("\n".join(ta))>60000 or len("\n".join(tb))>60000,"unified_diff":diff[:100000]},[f],["Text comparison is not an assessment of legal effect. Check the amending act and transitional provisions."],truncated=len(diff)>100000)


def borme_company_notices(company: str, date: str, province: str = "MADRID", limit: int = 20) -> dict[str, Any]:
    """Find corporate-name matches in one province's BORME registered-acts issue. Preserves official records; not a complete company history or credit assessment."""
    company = text_input(company,"company",160,False)
    if len(company)<3:
        raise SourceError("invalid_input","Use at least three characters of a company name.")
    province = text_input(province,"province",80,False); d=date_input(date); integer(limit,"limit",1,50)
    summary = CLIENT.get(f"{BOE}/datosabiertos/api/borme/sumario/{d:%Y%m%d}")
    items = [r for r in bulletin_items(_bulletin_data(summary)) if fold(r.get("titulo",""))==fold(province) and r.get("identificador","").startswith("BORME-A-")]
    if not items:
        return envelope([], [summary], ["No matching province issue was present on this date. This does not prove that the company has no filings."],date=d.isoformat(),province=province,documents_scanned=0,complete_company_history=False)
    sources=[summary]; rows=[]; matches=0
    for item in items[:3]:
        ident=item["identificador"]
        if not re.fullmatch(r"BORME-A-\d{4}-\d{1,4}-\d{2}",ident):
            continue
        f=CLIENT.get(f"{BOE}/diario_borme/xml.php",{"id":ident},accept="application/xml"); sources.append(f)
        root=f.xml(); text=root.find("texto")
        records=[]; current=None
        for p in text if text is not None else []:
            content=inner_text(p)
            if p.get("class")=="articulo":
                if current: records.append(current)
                current={"heading":content,"paragraphs":[]}
            elif current is not None:
                current["paragraphs"].append(content)
        if current: records.append(current)
        for r in records:
            if all(term in fold(r["heading"]) for term in fold(company).split()):
                matches+=1
                if len(rows)<limit:
                    rows.append({"heading":r["heading"],"text":"\n".join(r["paragraphs"]),"document_id":ident,"official_url":f"{BOE}/diario_borme/txt.php?id={ident}","publication_date":d.isoformat(),"province":province})
    return envelope(rows,sources,["Company-name matching is not identity proof. Resolve company name and registry identifiers, distinguish filing/publication/event dates, and inspect later corrections. Do not infer insolvency or misconduct from a notice."],date=d.isoformat(),province=province,documents_scanned=len(sources)-1,matches=matches,returned=len(rows),truncated=matches>limit,complete_company_history=False)


def _reference(reference: str) -> str:
    if not isinstance(reference,str):
        raise SourceError("invalid_input","reference must be a string.")
    reference=reference.strip().upper()
    if not re.fullmatch(r"(?:[A-Z0-9]{14}|[A-Z0-9]{18}|[A-Z0-9]{20})",reference):
        raise SourceError("invalid_input","Use a 14-, 18- or 20-character cadastral reference, not a person or tax identifier.")
    return reference


def catastro_property(reference: str) -> dict[str, Any]:
    """Retrieve only non-protected cadastral property facts from the official service. No owners, tax identifiers, cadastral valuations or title certification."""
    reference=_reference(reference)
    f=CLIENT.get(f"{CATASTRO}/COVCCallejero.svc/json/Consulta_DNPRC",{"Provincia":"","Municipio":"","RefCat":reference})
    body=f.json().get("consulta_dnprcResult")
    if not isinstance(body,dict):
        raise SourceError("schema_changed","Catastro did not return the expected non-protected-data result.",f.url)
    if body.get("lerr"):
        raise SourceError("source_reported_error","The cadastral service reported an error for this reference; no property facts were inferred.",f.url)
    bico=body.get("bico") or {}; bi=bico.get("bi") or {}; details=bi.get("debi") or {}; parcel=bico.get("finca") or {}
    constructions=[{"use":c.get("lcd"),"area_m2":(c.get("dfcons") or {}).get("stl"),"type":(c.get("dvcons") or {}).get("dtip")} for c in as_list(bico.get("lcons")) if isinstance(c,dict)]
    data={"reference":reference,"address":bi.get("ldt"),"use":details.get("luso"),"built_area_m2":details.get("sfc"),"construction_year":details.get("ant"),"participation_percent":details.get("cpt"),"parcel_area_m2":(parcel.get("dff") or {}).get("ss"),"parcel_type":parcel.get("ltp"),"map_url":(parcel.get("infgraf") or {}).get("igraf"),"construction_units":constructions}
    if not bi:
        if not body.get("lrcdnp"):raise SourceError("schema_changed","No property or candidate-property records were returned.",f.url)
        data["candidate_properties"]=body["lrcdnp"]
    return envelope(data,[f],["Source: Dirección General del Catastro. Non-protected descriptive data only. Cadastre is not proof of title, planning permission, occupancy legality, boundaries on the ground or market value. Navarra and the Basque Country have separate cadastral systems."],single_property=bool(bi))


def catastro_coordinates(reference: str) -> dict[str, Any]:
    """Return labelled longitude/latitude in EPSG:4326 from the official cadastral reference point, not a surveyed boundary."""
    reference=_reference(reference)
    f=CLIENT.get(f"{CATASTRO}/COVCCoordenadas.svc/json/Consulta_CPMRC",{"Provincia":"","Municipio":"","SRS":"EPSG:4326","RefCat":reference[:14]})
    body=f.json();result=body.get("Consulta_CPMRCResult") if isinstance(body,dict) else None
    if not isinstance(result,dict):raise SourceError("schema_changed","Missing cadastral coordinates response.",f.url)
    if result.get("lerr"):raise SourceError("source_reported_error","Catastro reported a coordinate error.",f.url)
    points=(result.get("coordenadas") or {}).get("coord");rows=[]
    for item in as_list(points):
        geo=item.get("geo",{})
        if geo.get("srs")!="EPSG:4326":raise SourceError("schema_changed","Unexpected coordinate reference system.",f.url)
        try:lon=float(geo['xcen']);lat=float(geo['ycen'])
        except (KeyError,TypeError,ValueError):raise SourceError("schema_changed","Invalid coordinate values.",f.url)
        if not(math.isfinite(lon) and math.isfinite(lat) and -180<=lon<=180 and -90<=lat<=90):raise SourceError("schema_changed","Coordinate values are out of range.",f.url)
        rows.append({"longitude":lon,"latitude":lat,"crs":"EPSG:4326","label":item.get("ldt")})
    if not rows:raise SourceError("source_not_found","No reference point was returned.",f.url)
    return envelope({"reference":reference,"points":rows},[f],["Reference points only, not surveyed boundaries; longitude and latitude are explicitly labelled."],reference=reference,crs="EPSG:4326")


def ine_operations(query: str = "", limit: int = 30, offset: int = 0) -> dict[str, Any]:
    """Discover official INE statistical operations by name. Use returned operation IDs; do not guess table IDs or series codes."""
    query=text_input(query,"query"); integer(limit,"limit",1,100)
    integer(offset,"offset",0,100000)
    f=CLIENT.get(f"{INE}/OPERACIONES_DISPONIBLES")
    body=f.json()
    if not isinstance(body,list): raise SourceError("schema_changed","Expected an INE operations array.",f.url)
    rows=[r for r in body if all(t in fold(r.get("Nombre","")) for t in fold(query).split())]
    return envelope(rows[offset:offset+limit],[f],[],matches=len(rows),truncated=offset+limit<len(rows),offset=offset,next_offset=offset+limit if offset+limit<len(rows) else None)


def ine_tables(operation_id: int, query: str = "", limit: int = 30, offset: int = 0) -> dict[str, Any]:
    """List tables for an INE operation, optionally filtering titles. Retrieves catalog metadata, not observations."""
    integer(operation_id,"operation_id",1,100000); integer(limit,"limit",1,100); query=text_input(query,"query")
    integer(offset,"offset",0,100000)
    f=CLIENT.get(f"{INE}/TABLAS_OPERACION/{operation_id}")
    body=f.json()
    if not isinstance(body,list): raise SourceError("schema_changed","Expected an INE tables array.",f.url)
    rows=[r for r in body if all(t in fold(r.get("Nombre","")) for t in fold(query).split())]
    return envelope(rows[offset:offset+limit],[f],[],matches=len(rows),truncated=offset+limit<len(rows),offset=offset,next_offset=offset+limit if offset+limit<len(rows) else None)


def ine_table_series(table_id: int, page: int = 1, query: str = "", limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Discover series codes in one INE table page. Native provider pagination begins at page 1; output may be filtered locally."""
    integer(table_id,"table_id",1,10000000); integer(page,"page",1,10000);integer(limit,"limit",1,100);query=text_input(query,"query")
    integer(offset,"offset",0,100000)
    f=CLIENT.get(f"{INE}/SERIES_TABLA/{table_id}",{"page":page})
    body=f.json()
    if not isinstance(body,list): raise SourceError("schema_changed","Expected an INE series array.",f.url)
    rows=[r for r in body if all(t in fold(r.get("Nombre","")) for t in fold(query).split())]
    return envelope(rows[offset:offset+limit],[f],["This is one provider page; an empty filtered page does not mean no matching series exist elsewhere in the table."],page=page,provider_records=len(body),matches_on_page=len(rows),truncated=offset+limit<len(rows),offset=offset,next_offset=offset+limit if offset+limit<len(rows) else None,next_page=page if offset+limit<len(rows) else page+1 if body else None,exhaustive=False)


def ine_series(series_code: str, last: int = 12) -> dict[str, Any]:
    """Retrieve INE series observations with metadata, source dates and an age warning. 'Latest in this series' does not imply the current statistical base."""
    if not isinstance(series_code,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,39}",series_code):
        raise SourceError("invalid_input","Use an INE series code returned by the catalog.")
    integer(last,"last",1,100)
    f=CLIENT.get(f"{INE}/DATOS_SERIE/{series_code}",{"nult":last,"tip":"AM"})
    body=f.json()
    if not isinstance(body,dict) or "Data" not in body:
        raise SourceError("schema_changed","INE did not return a data-series object.",f.url)
    dates=[]
    for observation in body.get("Data",[]):
        value=observation.get("Fecha")
        try:
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                dates.append(dt.datetime.fromtimestamp(value/1000,MADRID).date())
            elif isinstance(value,str):
                stamp=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
                dates.append(stamp.astimezone(MADRID).date() if stamp.tzinfo else stamp.date())
        except (ValueError,OverflowError,OSError):
            continue
    latest=max(dates) if dates else None
    age=(dt.datetime.now(MADRID).date()-latest).days if latest else None
    warnings=["Preserve units, scale, geography, frequency, base year, seasonal adjustment and provisional/confidential flags. Never compare unlike series or treat missing values as zero. Observation dates describe statistical periods, not retrieval dates."]
    if age is not None and age>120:
        warnings.append("The newest observation in this series is over 120 days old. This can be normal for annual series or indicate a discontinued/rebased series; check the operation's current tables before calling it current.")
    return envelope(body,[f],warnings,latest_observation_date=latest.isoformat() if latest else None,latest_observation_age_days=age)


def language_value(value: Any, language: str = "es") -> Any:
    vals=as_list(value)
    for v in vals:
        if isinstance(v,dict) and v.get("_lang")==language: return v.get("_value")
    for v in vals:
        if isinstance(v,dict) and "_value" in v: return v["_value"]
    return value


def normalize_dataset(r: dict[str, Any]) -> dict[str, Any]:
    distributions=[]
    for d in as_list(r.get("distribution")):
        if isinstance(d,dict):
            distributions.append({"title":language_value(d.get("title")),"format":d.get("format"),"access_url":d.get("accessURL"),"download_url":d.get("downloadURL"),"license":d.get("license"),"byte_size":d.get("byteSize")})
    return {"dataset_id":urllib.parse.urlsplit(r.get("_about","")).path.rstrip("/").rsplit("/",1)[-1],"catalog_url":r.get("_about"),"title":language_value(r.get("title")),"description":language_value(r.get("description")),"publisher":r.get("publisher"),"issued":r.get("issued"),"modified":r.get("modified"),"license":r.get("license"),"spatial":r.get("spatial"),"temporal":r.get("temporal"),"distributions":distributions}


def open_data_search(query: str, page: int = 0, page_size: int = 10) -> dict[str, Any]:
    """Search titles in the official datos.gob.es metadata catalog. Returns original publishers and distribution links; it does not ingest third-party datasets."""
    query=text_input(query,"query",160,False);integer(page,"page",0,10000);integer(page_size,"page_size",1,50)
    f=CLIENT.get(f"{DATOS}/title/{urllib.parse.quote(query,safe='')}.json",{"_page":page,"_pageSize":page_size})
    raw=f.json();body=raw.get("result") if isinstance(raw,dict) else None
    if not isinstance(body,dict) or not isinstance(body.get("items"),list):raise SourceError("schema_changed","Expected a catalog items array; no empty search was inferred.",f.url)
    rows=[normalize_dataset(r) for r in as_list(body.get("items")) if isinstance(r,dict)]
    return envelope(rows,[f],["Catalog metadata may be stale. Verify the original publisher, download availability, dataset-specific reuse licence, schema, units and update date before using data. No downstream distribution URL is fetched automatically."],page=page,page_size=page_size,next_page=page+1 if body.get("next") else None)


def open_data_dataset(dataset_id: str) -> dict[str, Any]:
    """Read one datos.gob.es dataset metadata record by its catalog slug, preserving licence and download references."""
    if not isinstance(dataset_id,str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,249}",dataset_id):
        raise SourceError("invalid_input","dataset_id must be a catalog slug returned by search, not a URL.")
    f=CLIENT.get(f"{DATOS}/{dataset_id}.json")
    result=f.json().get("result",{})
    item=result.get("primaryTopic")
    if not isinstance(item,dict):
        items=as_list(result.get("items")); item=items[0] if items else None
    if not isinstance(item,dict): raise SourceError("schema_changed","No dataset metadata record was returned.",f.url)
    return envelope(normalize_dataset(item),[f],["Rights in each dataset and distribution are separate from the MIT licence on this software. Missing licence metadata is not permission to redistribute."],dataset_id=dataset_id)

def ayudas_shortlist(query: str, page: int = 0, limit: int = 5, as_of: str = "") -> dict[str, Any]:
    """Search and inspect up to five BDNS records. Distinguishes date triage and direct-award signals from verified eligibility; partial failures stay visible."""
    integer(limit,"limit",1,5);day=date_input(as_of).isoformat()
    search=ayudas_search(query,page=page,page_size=limit);rows=[];sources=list(search['sources']);errors=[]
    for row in search['data']:
        try:
            result=ayudas_call(row['bdns_number']);detail=result['data'];sources.extend(result['sources'])
            label=fold(str(detail.get('tipoConvocatoria',''))+' '+str(detail.get('descripcion','')))
            direct=any(word in label for word in ('nominativa','concesion directa','subvencion directa'))
            rows.append({**row,'call_type':detail.get('tipoConvocatoria'),'direct_award_signal':direct,'budget_total_eur':detail.get('presupuestoTotal'),'beneficiary_types':detail.get('tiposBeneficiarios'),'regions':detail.get('regiones'),'deadline_assessment':deadline_assessment(detail.get('fechaInicioSolicitud'),detail.get('fechaFinSolicitud'),day),'bases_url':detail.get('urlBasesReguladoras'),'application_url':detail.get('sedeElectronica'),'raw_abierto':detail.get('abierto'),'application_status':'official_bases_and_portal_not_verified'})
        except SourceError as exc:
            error={'bdns_number':row['bdns_number'],'code':exc.code,'message':str(exc),'source_url':exc.source_url};errors.append(error);rows.append({**row,'detail_error':error})
    result={'ok':True,'data':rows,'sources':list({x['url']:x for x in sources}.values()),'coverage':{**search['coverage'],'details_checked':len(rows)-len(errors),'partial':bool(errors),'as_of':day},'warnings':search['warnings']+['Date triage is not an open-call certification. The source abierto flag is preserved, not used as a definitive open/closed flag. Direct-award text signals require checking the actual legal bases.'],'notice':SOURCE_NOTICE}
    if errors:result['errors']=errors
    return result


def borme_company_range(company: str, start_date: str, end_date: str, province: str = "MADRID", limit: int = 20) -> dict[str, Any]:
    """Inspect one company/province over up to seven explicit days, preserving missing issues and failures. User-initiated lookup, not monitoring."""
    start,end=date_input(start_date),date_input(end_date)
    if not start_date or not end_date or not 0<=(end-start).days<=6:raise SourceError("invalid_input","Choose an explicit inclusive range of 1–7 days.")
    company=text_input(company,"company",160,False);province=text_input(province,"province",80,False);integer(limit,"limit",1,50)
    if len(company)<3:raise SourceError("invalid_input","Use at least three characters of a company name.")
    rows=[];sources=[];days=[];errors=[];truncated=False
    for offset in range((end-start).days+1):
        day=(start+dt.timedelta(days=offset)).isoformat()
        try:
            item=borme_company_notices(company,day,province,limit)
            days.append({'date':day,'status':'checked','matches':item['coverage'].get('matches',0),'documents_scanned':item['coverage']['documents_scanned']})
            rows.extend(item['data']);sources.extend(item['sources']);truncated|=item['coverage'].get('truncated',False)
        except SourceError as exc:
            error={'date':day,'code':exc.code,'message':str(exc),'source_url':exc.source_url};errors.append(error);days.append({'date':day,'status':'unavailable','error':error})
    out={'ok':len(errors)<len(days),'data':rows[:limit],'sources':list({x['url']:x for x in sources}.values()),'coverage':{'company_query':company,'province':province,'start_date':start_date,'end_date':end_date,'days':days,'partial':bool(errors),'returned':min(limit,len(rows)),'truncated':truncated or len(rows)>limit,'complete_company_history':False},'warnings':['A missing/unavailable issue is not a no-filings result. Names are matches, not certified entity identity. No automatic monitoring is running.'],'notice':SOURCE_NOTICE}
    if errors:out['errors']=errors
    if not out['ok']:out['error']={'code':'source_unavailable','message':'No day in the requested range could be checked.'}
    return out


def licita_triage(query: str = "", cpv_prefix: str = "", max_pages: int = 1, limit: int = 15, cursor: str = "", offset: int = 0, deadline_from: str = "") -> dict[str, Any]:
    """Fast triage of one bounded official PLACSP feed window. A date bucket is not a bid/no-bid determination."""
    base=licita_search(query=query,cpv_prefix=cpv_prefix,max_pages=max_pages,limit=limit,cursor=cursor,offset=offset,deadline_from=deadline_from)
    rows=[];counts={}
    for item in base['data']:
        flag=item.get('deadline_assessment',{}).get('date_state','deadline_not_established')
        if flag in ('past_end_date',):bucket='published_deadline_passed'
        elif flag in ('within_published_dates','ends_today_check_time','end_date_ahead_start_unverified'):bucket='published_deadline_requires_verification'
        else:bucket='deadline_or_status_unknown'
        counts[bucket]=counts.get(bucket,0)+1
        rows.append({**item,'review_bucket':bucket,'next_action':'Check the current official contracting profile, all lots, PCAP/PPT, corrections and procedure status before deciding whether to bid.'})
    out={**base,'data':rows,'coverage':{**base['coverage'],'buckets_in_returned_rows':counts},'warnings':base.get('warnings',[])+['These are date-based and unknown-status triage buckets, not confirmation that a call is open, that you qualify or that any filing was submitted.']}
    return out


def ayudas_opportunities(query: str, page: int = 0, limit: int = 5, as_of: str = "") -> dict[str, Any]:
    """Actionability triage of up to five BDNS records based on published fields; no invented eligibility or grant approval."""
    base=ayudas_shortlist(query,page,limit,as_of)
    categories={'review_dates_and_bases':0,'possible_direct_award':0,'published_deadline_passed':0,'details_unavailable':0}
    ranked=[]
    for row in base['data']:
        state=(row.get('deadline_assessment') or {}).get('date_state','deadline_not_established')
        if row.get('detail_error'):category='details_unavailable'
        elif row.get('direct_award_signal'):category='possible_direct_award'
        elif state=='past_end_date':category='published_deadline_passed'
        else:category='review_dates_and_bases'
        categories[category]+=1
        ranked.append({**row,'review_bucket':category,'next_action':'Read the complete bases, eligible beneficiaries, later amendments and actual submission portal.'})
    ordered={'review_dates_and_bases':0,'details_unavailable':1,'possible_direct_award':2,'published_deadline_passed':3}
    ranked.sort(key=lambda x:(ordered[x['review_bucket']],str((x.get('deadline_assessment') or {}).get('end_date') or '9999')))
    return {**base,'data':ranked,'coverage':{**base['coverage'],'buckets_in_returned_rows':categories},'warnings':base.get('warnings',[])+['Triage order is a review order only, not a recommendation that an applicant qualifies.']}


def boe_find_articles(law_id: str, query: str, as_of: str = "", offset: int = 0, limit: int = 10, search_text: bool = False) -> dict[str, Any]:
    """Locate block IDs by article title (and optionally text) before version comparison. Searches one named consolidated law."""
    q=text_input(query,'query',120,False);integer(offset,'offset',0,100000);integer(limit,'limit',1,30)
    if not isinstance(search_text,bool):raise SourceError('invalid_input','search_text must be true or false.')
    day=date_input(as_of);f,blocks=_law(law_id);terms=fold(q).split();matches=[]
    for block in blocks:
        title=block.get('titulo') or '';selected=_version(block,day);body=inner_text(selected) if selected is not None else ''
        haystack=fold(title+' '+body) if search_text else fold(title)
        if all(term in haystack for term in terms):
            matches.append({'block_id':block.get('id'),'title':title,'type':block.get('tipo'),'selected_version':dict(selected.attrib) if selected is not None else None,'excerpt':body[:450] if selected is not None else None,'text_searched':search_text})
    return envelope(matches[offset:offset+limit],[f],['Search covers only this law and the selected date. A matched article is not a finding of legal applicability. Use boe_compare with its returned block_id and explicit dates.'],law_id=law_id,query=q,as_of=day.isoformat(),matches=len(matches),returned=len(matches[offset:offset+limit]),next_offset=offset+limit if offset+limit<len(matches) else None,search_text=search_text)


_BORME_EVENTS=(('incorporation',r'\bconstitucion\b'),('dissolution',r'\bdisolucion\b'),('registered_office_change',r'\bcambio de domicilio\b'),('appointment',r'\bnombramientos?\b'),('resignation',r'\bceses?\b|\bdimisiones?\b'),('capital_increase',r'\bampliacion de capital\b'),('capital_reduction',r'\breduccion de capital\b'),('correction',r'\bfe de erratas\b|\brectificacion\b'),('insolvency_proceeding',r'\bconcurso\b'))


def borme_events(company: str, start_date: str, end_date: str, province: str = 'MADRID', limit: int = 20) -> dict[str, Any]:
    """Classify dated BORME company notices conservatively using visible keyword rules; no credit/fraud predictions."""
    base=borme_company_range(company,start_date,end_date,province,limit)
    rows=[];counts={}
    for row in base['data']:
        body=fold(row.get('text') or '')
        categories=[key for key,pattern in _BORME_EVENTS if re.search(pattern,body)] or ['unclassified']
        for key in categories:counts[key]=counts.get(key,0)+1
        rows.append({**row,'event_categories':categories,'classification':'keyword_heuristic_not_certified'})
    return {**base,'data':rows,'coverage':{**base['coverage'],'event_category_counts_in_returned_rows':counts},'warnings':base.get('warnings',[])+['Event categories are deterministic keyword signals applied to the preserved official notice text, not certified company status, economic risk or beneficial ownership.']}


def catastro_ficha(reference: str) -> dict[str, Any]:
    """One-call public cadastral description and coordinate reference point with visible partial failures."""
    property_result=catastro_property(reference)
    errors=[];coordinate=None;source_records=property_result['sources'][:]
    try:
        position=catastro_coordinates(reference);source_records.extend(position['sources']);coordinate=position['data']
    except SourceError as exc:
        errors.append({'component':'coordinates','code':exc.code,'message':str(exc),'source_url':exc.source_url})
    out={'ok':True,'data':{'property':property_result['data'],'coordinates':coordinate,'title_verified':False,'planning_verified':False},'sources':source_records,'coverage':{'reference':reference,'description_checked':True,'coordinate_checked':coordinate is not None,'partial':bool(errors)},'warnings':property_result['warnings']+['A reference point is not a surveyed boundary. A cadastral description is not evidence of ownership, legal occupation, or planning permission.'],'notice':SOURCE_NOTICE}
    if errors:out['errors']=errors
    return out


def ine_series_change(series_code: str, last: int = 12) -> dict[str, Any]:
    """Compare the last two non-confidential numerical observations in an INE series, without inventing frequency or annualised growth."""
    base=ine_series(series_code,last);body=base['data'];entries=[]
    for r in as_list(body.get('Data')):
        if not isinstance(r,dict) or r.get('Secreto') is True:continue
        v=r.get('Valor')
        if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v):continue
        when=r.get('Fecha')
        try:
            if isinstance(when,(int,float)) and not isinstance(when,bool):day=dt.datetime.fromtimestamp(when/1000,MADRID).date()
            elif isinstance(when,str):
                stamp=dt.datetime.fromisoformat(when.replace('Z','+00:00'));day=stamp.astimezone(MADRID).date() if stamp.tzinfo else stamp.date()
            else:continue
        except (OverflowError,ValueError,OSError):continue
        entries.append((day,v,r))
    entries.sort(key=lambda x:x[0]);uniq={x[0]:x for x in entries};values=list(uniq.values())
    if len(values)<2:raise SourceError('insufficient_observations','Fewer than two comparable non-confidential numeric observations were returned. No change was inferred.')
    (older_date,older,older_raw),(newer_date,newer,newer_raw)=values[-2:]
    delta=newer-older;percent=(delta/older*100) if older!=0 else None
    return {**base,'data':{'series_code':series_code,'series_name':body.get('Nombre'),'unit':body.get('T3_Unidad',body.get('FK_Unidad')),'scale':body.get('T3_Escala',body.get('FK_Escala')),'older_period':older_date.isoformat(),'newer_period':newer_date.isoformat(),'older_value':older,'newer_value':newer,'absolute_change':delta,'percentage_change':percent,'percentage_change_unavailable_reason':'zero_baseline' if older==0 else None,'older_record':older_raw,'newer_record':newer_raw},'coverage':{**base['coverage'],'observations_requested':last,'non_confidential_numeric_periods':len(values)},'warnings':base.get('warnings',[])+['This is a two-observation arithmetic comparison, not an annualised rate or a statement about statistical significance. Check units, base, adjustments, provisional flags and comparability before interpreting it.']}


def open_data_compare(query: str, page: int = 0, page_size: int = 8) -> dict[str, Any]:
    """Compare dataset catalog metadata and verification gaps without fetching downstream files or certifying licences."""
    base=open_data_search(query,page,page_size);rows=[]
    for row in base['data']:
        dist=as_list(row.get('distributions'))
        formats=sorted({str(d.get('format')).rsplit('/',1)[-1] for d in dist if isinstance(d,dict) and d.get('format')})
        links=[url for d in dist if isinstance(d,dict) for url in [d.get('download_url') or d.get('access_url')] if isinstance(url,str) and url.strip()]
        declared=row.get('license')
        gaps=[]
        if not declared:gaps.append('licence_not_declared')
        if not links:gaps.append('no_distribution_link')
        if not row.get('modified'):gaps.append('catalog_update_date_missing')
        rows.append({**row,'formats':formats,'distribution_count':len(dist),'declared_licence':declared,'catalog_metadata_gaps':gaps,'download_checked':False,'distribution_schema_checked':False,'reuse_rights_verified':False})
    return {**base,'data':rows,'coverage':{**base['coverage'],'compared':len(rows),'only_catalog_metadata':True},'warnings':base.get('warnings',[])+['This comparison identifies metadata and missing checks, not working downloads, valid permission to reuse, observed data freshness or data quality.']}

PRODUCT_TOOLS: dict[str,list[Callable[...,dict[str,Any]]]] = {
    "licita-espana":[licita_search,licita_triage],
    "ayudas-espana":[ayudas_search,ayudas_call,ayudas_shortlist,ayudas_opportunities],
    "boe-impact":[boe_daily,boe_document,boe_consolidated,boe_compare,boe_find_articles],
    "borme-intelligence":[borme_company_notices,borme_company_range,borme_events],
    "catastro-pro":[catastro_property,catastro_coordinates,catastro_ficha],
    "ine-evidence":[ine_operations,ine_tables,ine_table_series,ine_series,ine_series_change],
    "spain-open-data":[open_data_search,open_data_dataset,open_data_compare],
}
TOOLS = {f.__name__:f for functions in PRODUCT_TOOLS.values() for f in functions}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(name, str) or name not in TOOLS:
        return {"ok":False,"error":{"code":"unknown_tool","message":"Unknown tool name."}}
    if not isinstance(arguments,dict):
        return {"ok":False,"error":{"code":"invalid_input","message":"Tool arguments must be a JSON object."}}
    try:
        # Bind first so malformed invocations cannot hide parser bugs as input mistakes.
        import inspect
        inspect.signature(TOOLS[name]).bind(**arguments)
    except TypeError:
        return {"ok":False,"error":{"code":"invalid_input","message":"Arguments do not match this tool's signature."}}
    try:
        return TOOLS[name](**arguments)
    except SourceError as exc:
        return {"ok":False,"error":{"code":exc.code,"message":str(exc),"source_url":exc.source_url},"notice":SOURCE_NOTICE}
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError):
        return {"ok":False,"error":{"code":"schema_changed","message":"The official response no longer matches the parser; no result was inferred."},"notice":SOURCE_NOTICE}
