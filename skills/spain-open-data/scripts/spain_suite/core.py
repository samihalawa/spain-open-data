"""Bounded, read-only access to Spain's official public data. Python 3.11+."""
from __future__ import annotations

import copy
import datetime as dt
import difflib
import hashlib
import json
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

VERSION = "0.1.2"
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
    p = urllib.parse.urlsplit(url)
    try:
        bad_port = p.port not in (None, 443)
    except ValueError:
        bad_port = True
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password or bad_port or p.fragment:
        raise SourceError("blocked_url", "Only HTTPS requests to the configured official-source allowlist are permitted.")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Fetch:
    body: bytes
    url: str
    fetched_at: str
    content_type: str
    cached: bool = False

    def provenance(self) -> dict[str, Any]:
        return {"url": self.url, "retrieved_at": self.fetched_at, "sha256": hashlib.sha256(self.body).hexdigest(), "cache_hit": self.cached}

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceError("invalid_response", "The source did not return valid JSON.", self.url) from exc

    def xml(self) -> ET.Element:
        # Reject DTD/entity declarations before using the standard-library XML parser.
        if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", self.body, re.I):
            raise SourceError("unsafe_xml", "DTD/entity declarations are not accepted.", self.url)
        try:
            return ET.fromstring(self.body)
        except ET.ParseError as exc:
            raise SourceError("invalid_response", "The source did not return valid XML.", self.url) from exc


class OfficialClient:
    """TLS-verified, bounded reads; no cookies, credentials, analytics or disk cache."""
    def __init__(self, ttl: int = 300, max_cache_bytes: int = 32 * 1024 * 1024):
        self.ttl, self.max_cache_bytes = ttl, max_cache_bytes
        self.cache: OrderedDict[str, tuple[float, Fetch]] = OrderedDict()
        self.lock = threading.Lock()
        self.last_request: dict[str, float] = {}
        self.opener = urllib.request.build_opener(_SafeRedirect())

    def get(self, url: str, params: dict[str, Any] | None = None, accept: str = "application/json") -> Fetch:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        safe_url(url)
        key = accept + " " + url
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < self.ttl:
                f = cached[1]
                return Fetch(f.body, f.url, f.fetched_at, f.content_type, True)
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
                    chunks, total = [], 0
                    while True:
                        part = response.read(65536)
                        if not part:
                            break
                        total += len(part)
                        if total > MAX_BYTES:
                            raise SourceError("response_too_large", "Official response exceeds the 8 MiB safety limit; narrow the query.", url)
                        chunks.append(part)
                    f = Fetch(b"".join(chunks), response.geturl(), dt.datetime.now(dt.timezone.utc).isoformat(), response.headers.get("Content-Type", ""))
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


def licita_search(query: str = "", cpv_prefix: str = "", max_pages: int = 1, limit: int = 20, cursor: str = "") -> dict[str, Any]:
    """Search a bounded window of PLACSP's official Atom feed, not all Spanish tenders. Returns a continuation cursor and explicit coverage. Does not submit bids."""
    query = text_input(query, "query")
    cpv_prefix = text_input(cpv_prefix, "cpv_prefix", 8)
    if cpv_prefix and not re.fullmatch(r"\d{2,8}", cpv_prefix):
        raise SourceError("invalid_input", "cpv_prefix must contain 2–8 digits.")
    integer(max_pages, "max_pages", 1, 3); integer(limit, "limit", 1, 50)
    url = PLACSP
    if cursor:
        safe_url(cursor)
        p = urllib.parse.urlsplit(cursor)
        if p.hostname != "contrataciondelestado.es" or p.query or not re.fullmatch(r"/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3(?:_[0-9_]+)?\.atom", p.path):
            raise SourceError("invalid_input", "cursor must be a continuation URL returned by this PLACSP feed.")
        url = cursor
    rows, sources, seen, deleted, visited = [], [], set(), set(), set()
    scanned = matched = 0
    next_url = None
    for _ in range(max_pages):
        if url in visited:
            break
        visited.add(url)
        f = CLIENT.get(url, accept="application/atom+xml")
        sources.append(f)
        root = f.xml()
        for tombstone in descendants(root, "deleted-entry"):
            deleted.add(tombstone.attrib.get("ref", ""))
        for entry in [e for e in root if local_name(e.tag) == "entry"]:
            eid = path_text(entry, "id")
            if not eid or eid in seen or eid in deleted:
                continue
            seen.add(eid); scanned += 1
            title = path_text(entry, "title") or ""
            searchable = fold(inner_text(entry))
            cpvs = [inner_text(e) for e in descendants(entry, "ItemClassificationCode")]
            if query and not all(term in searchable for term in fold(query).split()):
                continue
            if cpv_prefix and not any(c.startswith(cpv_prefix) for c in cpvs):
                continue
            matched += 1
            if len(rows) >= limit:
                continue
            status_nodes = descendants(entry, "ContractFolderStatus")
            status = status_nodes[0] if status_nodes else entry
            project = descendants(status, "ProcurementProject")
            budget = descendants(project[0], "BudgetAmount") if project else []
            parties = descendants(status, "LocatedContractingParty")
            deadlines = descendants(status, "TenderSubmissionDeadlinePeriod")
            docs = []
            for ref in descendants(status, "DocumentReference") + descendants(status, "LegalDocumentReference") + descendants(status, "TechnicalDocumentReference"):
                for u in descendants(ref, "URI"):
                    val = inner_text(u)
                    if val.startswith(("https://", "http://")):
                        docs.append(val)
            hrefs = [e.attrib.get("href") for e in entry if local_name(e.tag) == "link" and e.attrib.get("rel", "alternate") == "alternate"]
            rows.append({"id": eid, "title": title, "official_url": hrefs[0] if hrefs else eid, "updated": path_text(entry, "updated"), "reference": first_text(status, "ContractFolderID"), "status_code": first_text(status, "ContractFolderStatusCode"), "authority": first_text(parties[0], "Name") if parties else None, "cpv": cpvs, "budget_excluding_tax": first_text(budget[0], "TaxExclusiveAmount") if budget else None, "currency": next((e.attrib.get("currencyID") for e in budget[0] if local_name(e.tag) == "TaxExclusiveAmount"), None) if budget else None, "deadline_date": first_text(deadlines[0], "EndDate") if deadlines else None, "deadline_time": first_text(deadlines[0], "EndTime") if deadlines else None, "document_urls": list(dict.fromkeys(docs))})
        next_url = next((e.attrib.get("href") for e in root if local_name(e.tag) == "link" and e.attrib.get("rel") == "next"), None)
        if not next_url:
            break
        url = next_url
    warnings = ["Bounded feed search, not exhaustive national discovery. Recent feed updates can describe closed, awarded or cancelled tenders. Check the official procurement profile and full tender documents before deciding eligibility or deadlines."]
    if matched > len(rows):
        warnings.append("The result limit truncated matches within scanned pages. Increase limit or narrow the query; the cursor advances after the scanned pages.")
    return envelope(rows, sources, warnings, pages_scanned=len(sources), entries_scanned=scanned, matches_in_scanned_pages=matched, returned=len(rows), truncated=matched > len(rows), next_cursor=next_url, exhaustive=False)


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
    if not isinstance(body, dict) or not body:
        raise SourceError("schema_changed", "BDNS did not return a call object.", f.url)
    return envelope(body, [f], ["This is a published call record, not an eligibility determination. Official bases, amendments and the application portal take precedence. A direct award is not an open application opportunity."], bdns_number=bdns_number)


def boe_daily(date: str, query: str = "", limit: int = 30) -> dict[str, Any]:
    """Read a specific BOE issue and filter item titles. Returns official identifiers and links, not an exhaustive search of legislation."""
    d = date_input(date); query = text_input(query, "query"); integer(limit, "limit", 1, 100)
    f = CLIENT.get(f"{BOE}/datosabiertos/api/boe/sumario/{d:%Y%m%d}")
    body = f.json()
    items = list(bulletin_items(body.get("data", {})))
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
    return envelope({"law_id":law_id,"block_id":block_id,"older_version":dict(a.attrib),"newer_version":dict(b.attrib),"changed":ta!=tb,"unified_diff":diff[:100000]},[f],["Text comparison is not an assessment of legal effect. Check the amending act and transitional provisions."],truncated=len(diff)>100000)


def borme_company_notices(company: str, date: str, province: str = "MADRID", limit: int = 20) -> dict[str, Any]:
    """Find corporate-name matches in one province's BORME registered-acts issue. Preserves official records; not a complete company history or credit assessment."""
    company = text_input(company,"company",160,False)
    if len(company)<3:
        raise SourceError("invalid_input","Use at least three characters of a company name.")
    province = text_input(province,"province",80,False); d=date_input(date); integer(limit,"limit",1,50)
    summary = CLIENT.get(f"{BOE}/datosabiertos/api/borme/sumario/{d:%Y%m%d}")
    items = [r for r in bulletin_items(summary.json().get("data",{})) if fold(r.get("titulo",""))==fold(province) and r.get("identificador","").startswith("BORME-A-")]
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
    return envelope(rows,sources,["Company-name matching is not identity proof. Resolve company name and registry identifiers, distinguish filing/publication/event dates, and inspect later corrections. Do not infer insolvency or misconduct from a notice."],documents_scanned=len(sources)-1,matches=matches,returned=len(rows),truncated=matches>limit,complete_company_history=False)


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
        return envelope({"reference":reference,"source_errors":body["lerr"],"property":None},[f],["The cadastral service reported an error; no property facts were inferred."],matched=False)
    bico=body.get("bico") or {}; bi=bico.get("bi") or {}; details=bi.get("debi") or {}; parcel=bico.get("finca") or {}
    constructions=[{"use":c.get("lcd"),"area_m2":(c.get("dfcons") or {}).get("stl"),"type":(c.get("dvcons") or {}).get("dtip")} for c in as_list(bico.get("lcons")) if isinstance(c,dict)]
    data={"reference":reference,"address":bi.get("ldt"),"use":details.get("luso"),"built_area_m2":details.get("sfc"),"construction_year":details.get("ant"),"participation_percent":details.get("cpt"),"parcel_area_m2":(parcel.get("dff") or {}).get("ss"),"parcel_type":parcel.get("ltp"),"map_url":(parcel.get("infgraf") or {}).get("igraf"),"construction_units":constructions}
    if not bi:
        data["candidate_properties"]=body.get("lrcdnp",[])
    return envelope(data,[f],["Source: Dirección General del Catastro. Non-protected descriptive data only. Cadastre is not proof of title, planning permission, occupancy legality, boundaries on the ground or market value. Navarra and the Basque Country have separate cadastral systems."],single_property=bool(bi))


def catastro_coordinates(reference: str) -> dict[str, Any]:
    """Obtain the official cadastral reference point in EPSG:4326. It is not a parcel boundary or survey."""
    reference=_reference(reference)
    f=CLIENT.get(f"{CATASTRO}/COVCCoordenadas.svc/json/Consulta_CPMRC",{"Provincia":"","Municipio":"","SRS":"EPSG:4326","RefCat":reference[:14]})
    body=f.json()
    return envelope(body,[f],["Reference point only, not surveyed boundaries. Coordinate order must follow the source fields and CRS."],reference=reference,crs="EPSG:4326")


def ine_operations(query: str = "", limit: int = 30) -> dict[str, Any]:
    """Discover official INE statistical operations by name. Use returned operation IDs; do not guess table IDs or series codes."""
    query=text_input(query,"query"); integer(limit,"limit",1,100)
    f=CLIENT.get(f"{INE}/OPERACIONES_DISPONIBLES")
    body=f.json()
    if not isinstance(body,list): raise SourceError("schema_changed","Expected an INE operations array.",f.url)
    rows=[r for r in body if all(t in fold(r.get("Nombre","")) for t in fold(query).split())]
    return envelope(rows[:limit],[f],[],matches=len(rows),truncated=len(rows)>limit)


def ine_tables(operation_id: int, query: str = "", limit: int = 30) -> dict[str, Any]:
    """List tables for an INE operation, optionally filtering titles. Retrieves catalog metadata, not observations."""
    integer(operation_id,"operation_id",1,100000); integer(limit,"limit",1,100); query=text_input(query,"query")
    f=CLIENT.get(f"{INE}/TABLAS_OPERACION/{operation_id}")
    body=f.json()
    if not isinstance(body,list): raise SourceError("schema_changed","Expected an INE tables array.",f.url)
    rows=[r for r in body if all(t in fold(r.get("Nombre","")) for t in fold(query).split())]
    return envelope(rows[:limit],[f],[],matches=len(rows),truncated=len(rows)>limit)


def ine_table_series(table_id: int, page: int = 1, query: str = "", limit: int = 20) -> dict[str, Any]:
    """Discover series codes in one INE table page. Native provider pagination begins at page 1; output may be filtered locally."""
    integer(table_id,"table_id",1,10000000); integer(page,"page",1,10000);integer(limit,"limit",1,100);query=text_input(query,"query")
    f=CLIENT.get(f"{INE}/SERIES_TABLA/{table_id}",{"page":page})
    body=f.json()
    if not isinstance(body,list): raise SourceError("schema_changed","Expected an INE series array.",f.url)
    rows=[r for r in body if all(t in fold(r.get("Nombre","")) for t in fold(query).split())]
    return envelope(rows[:limit],[f],["This is one provider page; an empty filtered page does not mean no matching series exist elsewhere in the table."],page=page,provider_records=len(body),matches_on_page=len(rows),truncated=len(rows)>limit,next_page=page+1 if body else None,exhaustive=False)


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
    return {"catalog_url":r.get("_about"),"title":language_value(r.get("title")),"description":language_value(r.get("description")),"publisher":r.get("publisher"),"issued":r.get("issued"),"modified":r.get("modified"),"license":r.get("license"),"spatial":r.get("spatial"),"temporal":r.get("temporal"),"distributions":distributions}


def open_data_search(query: str, page: int = 0, page_size: int = 10) -> dict[str, Any]:
    """Search titles in the official datos.gob.es metadata catalog. Returns original publishers and distribution links; it does not ingest third-party datasets."""
    query=text_input(query,"query",160,False);integer(page,"page",0,10000);integer(page_size,"page_size",1,50)
    f=CLIENT.get(f"{DATOS}/title/{urllib.parse.quote(query,safe='')}.json",{"_page":page,"_pageSize":page_size})
    body=f.json().get("result",{})
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

PRODUCT_TOOLS: dict[str,list[Callable[...,dict[str,Any]]]] = {
    "licita-espana":[licita_search],
    "ayudas-espana":[ayudas_search,ayudas_call],
    "boe-impact":[boe_daily,boe_document,boe_consolidated,boe_compare],
    "borme-intelligence":[borme_company_notices],
    "catastro-pro":[catastro_property,catastro_coordinates],
    "ine-evidence":[ine_operations,ine_tables,ine_table_series,ine_series],
    "spain-open-data":[open_data_search,open_data_dataset],
}
TOOLS = {f.__name__:f for functions in PRODUCT_TOOLS.values() for f in functions}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
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
