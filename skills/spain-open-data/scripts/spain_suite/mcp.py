"""Product-scoped MCP over stdio; no shell, downloads, or credential config."""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import sys
from typing import get_type_hints

from . import core
from .presentation import render

PROTOCOLS = ("2025-11-25", "2025-06-18", "2024-11-05")
MAX_INPUT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
REFERENCE_ROOT = Path(__file__).resolve().parents[2] / "references"


class ProtocolError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError("Non-finite JSON number")


def _unicode_scalars(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            item.encode("utf-8")
        elif isinstance(item, dict):
            pending.extend(item)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _schema(function):
    properties, required = {}, []
    types = {str: "string", int: "integer", bool: "boolean"}
    hints = get_type_hints(function)
    for name, parameter in inspect.signature(function).parameters.items():
        entry = {"type": types[hints[name]]}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        else:
            entry["default"] = parameter.default
        properties[name] = entry
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


def _tool_result(payload):
    try:
        _unicode_scalars(payload)
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        payload = {"ok": False, "error": {"code": "invalid_response",
                    "message": "The source result was not valid JSON; no result inferred."}}
        text = json.dumps(payload)
    return {"content": [{"type": "text", "text": text}],
            "structuredContent": payload, "isError": payload.get("ok") is not True}


class Server:
    def __init__(self, reference_root=REFERENCE_ROOT):
        self.references = Path(reference_root)
        self.product = json.loads((self.references / "product.json").read_text(encoding="utf-8"))
        self.slug = self.product["slug"]
        self.functions = {f.__name__: f for f in core.PRODUCT_TOOLS[self.slug]}
        self.demo_name = self.slug.replace("-", "_") + "_demo"
        self.report_name = self.slug.replace("-", "_") + "_report"
        self.initialized = self.ready = False

    def tools(self):
        result = [{"name": name, "title": name.replace("_", " "),
                   "description": function.__doc__ or name,
                   "inputSchema": _schema(function),
                   "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                   "idempotentHint": True, "openWorldHint": True}}
                  for name, function in self.functions.items()]
        result.append({"name": self.demo_name, "title": self.product["name"] + " · ejemplo guardado",
                       "description": "Read the bundled dated example without network access. It is historical, never live.",
                       "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                       "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                       "idempotentHint": True, "openWorldHint": False}})
        result.append({"name": self.report_name, "title": self.product["name"] + " · informe",
                       "description": "Return a deterministic Markdown, HTML or JSON report for one product operation or the saved example. Writes no files; preserve source dates and partial coverage.",
                       "inputSchema": {"type": "object", "properties": {
                           "operation": {"type": "string", "enum": [*self.functions, self.demo_name]},
                           "arguments": {"type": "object", "default": {}},
                           "format": {"type": "string", "enum": ["markdown", "html", "json"], "default": "markdown"}},
                           "required": ["operation"], "additionalProperties": False},
                       "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                       "idempotentHint": True, "openWorldHint": True}})
        return result

    def _payload(self, name, arguments):
        if not isinstance(name, str) or name not in {*self.functions, self.demo_name}:
            raise ProtocolError(-32602, "Unknown tool for this product")
        if not isinstance(arguments, dict):
            raise ProtocolError(-32602, "Tool arguments must be an object")
        if name == self.demo_name:
            if arguments:
                raise ProtocolError(-32602, "The saved example takes no arguments")
            snapshot = json.loads((self.references / "demo.json").read_text(encoding="utf-8"))
            payload = copy.deepcopy(snapshot["result"])
            payload["example"] = {"captured_at": snapshot["captured_at"],
                                  "mode": "saved_official_snapshot", "live": False}
            operation = snapshot["tool"]
        else:
            payload = core.call_tool(name, arguments)
            operation = name
        return payload, operation

    def _call(self, params):
        name, arguments = params.get("name"), params.get("arguments", {})
        if name == self.report_name:
            if not isinstance(arguments, dict) or set(arguments) - {"operation", "arguments", "format"}:
                raise ProtocolError(-32602, "Invalid report arguments")
            format_name = arguments.get("format", "markdown")
            if format_name not in ("markdown", "html", "json"):
                raise ProtocolError(-32602, "Unsupported report format")
            payload, operation = self._payload(arguments.get("operation"), arguments.get("arguments", {}))
            text = render(payload, operation, self.product, format_name)
            payload = {"ok": payload.get("ok") is True, "data": {"format": format_name, "report": text},
                       "sources": payload.get("sources", []), "coverage": payload.get("coverage", {}),
                       "warnings": payload.get("warnings", []), "result": payload}
        else:
            payload, _ = self._payload(name, arguments)
        return _tool_result(payload)

    def handle(self, message):
        request_id = None
        if not isinstance(message, dict):
            return self.error(None, -32600, "Expected one JSON-RPC object")
        has_id = "id" in message
        request_id = message.get("id")
        valid_id = isinstance(request_id, (str, int)) and not isinstance(request_id, bool)
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str) or (has_id and not valid_id):
            return self.error(None, -32600, "Invalid JSON-RPC request")
        method, params = message["method"], message.get("params", {})
        if not has_id:
            # Notifications never invoke tools or perform source requests.
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None
        try:
            if not isinstance(params, dict):
                raise ProtocolError(-32602, "Parameters must be an object")
            if method == "ping":
                result = {}
            elif method == "initialize":
                if self.initialized:
                    raise ProtocolError(-32600, "Already initialized")
                version = params.get("protocolVersion")
                if not isinstance(version, str) or not version:
                    raise ProtocolError(-32602, "protocolVersion is required")
                result = {"protocolVersion": version if version in PROTOCOLS else PROTOCOLS[0],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": self.slug, "version": core.VERSION},
                          "instructions": "Read-only official-source queries for this product only. Check dates, source links, coverage and partial errors. Saved examples are historical. No filing, account credentials or background monitoring."}
                self.initialized = True
            elif not self.ready:
                raise ProtocolError(-32002, "Initialize the MCP session first")
            elif method == "tools/list":
                if params.get("cursor") is not None:
                    raise ProtocolError(-32602, "This bounded tool list has no continuation cursor")
                result = {"tools": self.tools()}
            elif method == "tools/call":
                result = self._call(params)
            else:
                raise ProtocolError(-32601, "Method not supported")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ProtocolError as exc:
            return self.error(request_id, exc.code, exc.message)
        except Exception:
            # Do not echo source text, user arguments, proxy configuration or paths.
            return self.error(request_id, -32603, "Tool processing failed; no result inferred")

    @staticmethod
    def error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": code, "message": message}}


def serve(source, destination, server=None):
    server = server or Server()
    while True:
        raw = source.readline(MAX_INPUT_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_INPUT_BYTES:
            while raw and not raw.endswith(b"\n"):
                raw = source.readline(MAX_INPUT_BYTES + 1)
            response = server.error(None, -32700, "MCP message exceeds the input byte limit")
        else:
            try:
                message = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                                     parse_constant=_bad_constant)
                _unicode_scalars(message)
            except (ValueError, UnicodeError, RecursionError):
                response = server.error(None, -32700, "Invalid UTF-8 JSON message")
            else:
                response = server.handle(message)
        if response is None:
            continue
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_OUTPUT_BYTES:
            if "content" in response.get("result", {}):
                response = {"jsonrpc": "2.0", "id": response.get("id"), "result": _tool_result({
                    "ok": False, "error": {"code": "response_too_large", "message":
                    "Tool output exceeds the MCP byte limit. Narrow the query; no complete result inferred."}})}
            else:
                response = server.error(response.get("id"), -32603, "MCP response exceeds the output byte limit")
            encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
        destination.write(encoded + b"\n")
        destination.flush()


def main():
    serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
