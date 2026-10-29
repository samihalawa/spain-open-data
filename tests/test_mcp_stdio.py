"""Product-scoped MCP contracts, malformed frames and real stdio round trips."""
from pathlib import Path
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SLUG = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())['name']
SCRIPTS = ROOT / 'skills' / SLUG / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from spain_suite import core, mcp


def request(method, params=None, request_id=1):
    return {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}}


def ready():
    server = mcp.Server()
    reply = server.handle(request('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                                'clientInfo': {'name': 'fixture-client', 'version': '1'}}))
    assert reply['result']['protocolVersion'] == '2025-11-25'
    server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    return server


class MCPContracts(unittest.TestCase):
    def test_only_product_tools_and_offline_example_are_exposed(self):
        server = ready()
        tools = server.handle(request('tools/list'))['result']['tools']
        self.assertEqual({t['name'] for t in tools}, {f.__name__ for f in core.PRODUCT_TOOLS[SLUG]} | {server.demo_name, server.report_name})
        for tool in tools:
            self.assertFalse(tool['inputSchema']['additionalProperties'])
            self.assertTrue(tool['annotations']['readOnlyHint'])
            self.assertFalse(tool['annotations']['destructiveHint'])

    def test_other_products_cannot_be_called(self):
        server = ready()
        name = next(n for n in core.TOOLS if n not in server.functions)
        with patch.object(core, 'call_tool') as call:
            result = server.handle(request('tools/call', {'name': name, 'arguments': {}}))
        self.assertEqual(result['error']['code'], -32602)
        call.assert_not_called()

    def test_tool_notifications_never_execute_queries(self):
        server = ready()
        with patch.object(core, 'call_tool') as call:
            reply = server.handle({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': next(iter(server.functions))}})
        self.assertIsNone(reply)
        call.assert_not_called()

    def test_initialization_required_before_tools(self):
        self.assertEqual(mcp.Server().handle(request('tools/list'))['error']['code'], -32002)

    def test_protocol_negotiation_and_repeated_initialization(self):
        server = mcp.Server()
        result = server.handle(request('initialize', {'protocolVersion': 'unsupported-version'}))
        self.assertEqual(result['result']['protocolVersion'], mcp.PROTOCOLS[0])
        self.assertEqual(server.handle(request('initialize', {'protocolVersion': mcp.PROTOCOLS[0]}))['error']['code'], -32600)

    def test_saved_example_is_explicitly_not_live(self):
        server = ready()
        with patch.object(core.CLIENT, 'get', side_effect=AssertionError('Network forbidden')):
            result = server.handle(request('tools/call', {'name': server.demo_name, 'arguments': {}}))['result']
        self.assertFalse(result['isError'])
        self.assertFalse(result['structuredContent']['example']['live'])
        self.assertEqual(result['structuredContent']['example']['mode'], 'saved_official_snapshot')

    def test_reports_preserve_deterministic_exports_without_file_writes(self):
        server = ready()
        for fmt in ('html', 'markdown', 'json'):
            with self.subTest(format=fmt), patch.object(core.CLIENT, 'get', side_effect=AssertionError('Network forbidden')):
                result = server.handle(request('tools/call', {'name': server.report_name, 'arguments': {
                    'operation': server.demo_name, 'format': fmt}}))['result']
            self.assertFalse(result['isError'])
            payload = result['structuredContent']
            self.assertFalse(payload['result']['example']['live'])
            self.assertTrue(payload['data']['report'])
            if fmt == 'html':
                self.assertIn('<html lang="es">', payload['data']['report'])
                self.assertNotIn('<script', payload['data']['report'].lower())
        self.assertEqual(server.handle(request('tools/call', {'name': server.report_name,
            'arguments': {'operation': server.report_name}}))['error']['code'], -32602)
        self.assertEqual(server.handle(request('tools/call', {'name': server.report_name,
            'arguments': {'operation': server.demo_name, 'output': '/tmp/unwanted-file'}}))['error']['code'], -32602)

    def test_known_tool_bad_arguments_are_not_an_empty_result(self):
        server = ready()
        with patch.object(core.CLIENT, 'get', side_effect=AssertionError('Network forbidden')):
            result = server.handle(request('tools/call', {'name': next(iter(server.functions)), 'arguments': {'unexpected_input': 'value'}}))['result']
        self.assertTrue(result['isError'])
        self.assertFalse(result['structuredContent']['ok'])

    def test_partial_source_labels_survive_the_protocol(self):
        server = ready()
        partial = {'ok': True, 'data': [], 'coverage': {'partial': True, 'unread_page_suffix': True},
                   'sources': [{'sha256_scope': 'response_prefix', 'complete': False}],
                   'warnings': ['Unexamined data may contain matches.']}
        with patch.object(core, 'call_tool', return_value=partial):
            result = server.handle(request('tools/call', {'name': next(iter(server.functions))}))['result']
        self.assertEqual(result['structuredContent'], partial)
        self.assertEqual(json.loads(result['content'][0]['text']), partial)

    def test_invalid_rpc_ids_and_parameters_are_errors(self):
        server = ready()
        for message in [[], {'jsonrpc': '1.0', 'id': 1, 'method': 'ping'},
                        {'jsonrpc': '2.0', 'id': True, 'method': 'ping'},
                        {'jsonrpc': '2.0', 'id': 1.5, 'method': 'ping'}]:
            self.assertEqual(server.handle(message)['error']['code'], -32600)
        self.assertEqual(server.handle({'jsonrpc': '2.0', 'id': 0, 'method': 'ping'})['id'], 0)
        self.assertEqual(server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': []})['error']['code'], -32602)
        self.assertEqual(server.handle(request('shell/execute'))['error']['code'], -32601)

    def test_list_cursor_and_demo_arguments_are_rejected(self):
        server = ready()
        self.assertEqual(server.handle(request('tools/list', {'cursor': 'untrusted'}))['error']['code'], -32602)
        self.assertEqual(server.handle(request('tools/call', {'name': server.demo_name, 'arguments': {'extra': True}}))['error']['code'], -32602)

    def test_malformed_frames_do_not_poison_the_next_request(self):
        bad = [b'not json\n', b'\xff\n', b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n',
               b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n',
               b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n',
               b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"\\udfff":1}}\n']
        for frame in bad:
            output = io.BytesIO()
            mcp.serve(io.BytesIO(frame + json.dumps(request('ping', request_id=4)).encode() + b'\n'), output)
            replies = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(replies[0]['error']['code'], -32700)
            self.assertEqual(replies[1], {'jsonrpc': '2.0', 'id': 4, 'result': {}})

    def test_deeply_nested_non_rpc_json_is_rejected_without_crashing(self):
        output = io.BytesIO()
        data = b'[' * 1500 + b']' * 1500 + b'\n' + json.dumps(request('ping', request_id=7)).encode() + b'\n'
        mcp.serve(io.BytesIO(data), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        # Valid JSON arrays are invalid RPC objects; stricter parser depth limits
        # can reject the same input earlier. Neither may poison the next frame.
        self.assertIn(replies[0]['error']['code'], (-32600, -32700))
        self.assertEqual(replies[1]['id'], 7)

    def test_invalid_unicode_from_a_provider_is_an_error_not_a_crash(self):
        server = ready()
        output = io.BytesIO()
        message = request('tools/call', {'name': next(iter(server.functions))}, request_id=8)
        data = (json.dumps(message) + '\n' + json.dumps(request('ping', request_id=9)) + '\n').encode()
        with patch.object(core, 'call_tool', return_value={'ok': True, 'data': '\ud800'}):
            mcp.serve(io.BytesIO(data), output, server)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(replies[0]['result']['isError'])
        self.assertEqual(replies[0]['result']['structuredContent']['error']['code'], 'invalid_response')
        self.assertEqual(replies[1]['id'], 9)

    def test_oversized_frame_is_drained_without_losing_framing(self):
        output = io.BytesIO()
        data = b'x' * 5000 + b'\n' + json.dumps(request('ping', request_id=5)).encode() + b'\n'
        with patch.object(mcp, 'MAX_INPUT_BYTES', 1000):
            mcp.serve(io.BytesIO(data), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(replies[0]['error']['code'], -32700)
        self.assertEqual(replies[1]['id'], 5)

    def test_oversized_tool_output_is_an_explicit_failure(self):
        server = ready()
        message = request('tools/call', {'name': next(iter(server.functions))}, request_id=6)
        output = io.BytesIO()
        with patch.object(core, 'call_tool', return_value={'ok': True, 'data': 'x' * 5000}), patch.object(mcp, 'MAX_OUTPUT_BYTES', 1000):
            mcp.serve(io.BytesIO(json.dumps(message).encode() + b'\n'), output, server)
        reply = json.loads(output.getvalue())
        self.assertTrue(reply['result']['isError'])
        self.assertEqual(reply['result']['structuredContent']['error']['code'], 'response_too_large')

    def test_real_stdio_process_handshake_list_and_offline_call(self):
        server = mcp.Server()
        messages = [request('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                         'clientInfo': {'name': 'stdio-test', 'version': '1'}}, 1),
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    request('tools/list', request_id=2),
                    request('tools/call', {'name': server.demo_name, 'arguments': {}}, 3)]
        raw = ''.join(json.dumps(message) + '\n' for message in messages)
        result = subprocess.run([sys.executable, str(SCRIPTS / 'mcp_server.py')], input=raw,
                                env={'PYTHONDONTWRITEBYTECODE': '1'}, text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies], [1, 2, 3])
        self.assertEqual(replies[0]['result']['serverInfo']['version'], core.VERSION)
        self.assertFalse(replies[2]['result']['structuredContent']['example']['live'])


if __name__ == '__main__':
    unittest.main()
