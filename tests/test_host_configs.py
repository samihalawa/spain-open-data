"""Exercise declared host commands with open stdio and transport disabled."""
from pathlib import Path
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
METADATA = json.loads((ROOT / 'plugin.json').read_text())
SLUG = METADATA['name']


class HostConfigurations(unittest.TestCase):
    def test_portable_marketplace_identifies_this_local_plugin(self):
        marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        interface = METADATA['extensions']['com.openai']['interface']
        self.assertEqual(marketplace['name'], SLUG)
        self.assertEqual(marketplace['interface']['displayName'], interface['displayName'])
        self.assertEqual(len(marketplace['plugins']), 1)
        plugin = marketplace['plugins'][0]
        self.assertEqual(plugin['name'], SLUG)
        self.assertEqual(plugin['source'], {'source': 'local', 'path': './'})
        self.assertEqual(plugin['policy'], {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'})
        self.assertEqual(plugin['category'], interface['category'])

    def test_declared_host_commands_respond_without_stdin_eof(self):
        for filename, variable in [('mcp.json', '${PLUGIN_ROOT}'), ('.mcp.json', '${CLAUDE_PLUGIN_ROOT}')]:
            with self.subTest(configuration=filename):
                config = json.loads((ROOT / filename).read_text())
                self.assertEqual(set(config['mcpServers']), {SLUG})
                server = config['mcpServers'][SLUG]
                self.assertEqual(server['command'], 'python3')
                self.assertEqual(server['args'], [variable + '/skills/' + SLUG + '/scripts/mcp_server.py'])
                if filename == 'mcp.json':
                    self.assertEqual(config['$schema'], 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json')
                    self.assertEqual(server['cwd'], variable)
                resolve = lambda text: text.replace(variable, str(ROOT))
                command = [server['command'], *map(resolve, server['args'])]
                with tempfile.TemporaryDirectory() as directory:
                    Path(directory, 'sitecustomize.py').write_text(
                        'import socket\n'
                        'def blocked(*args, **kwargs): raise RuntimeError("Network disabled in host configuration regression")\n'
                        'socket.create_connection = blocked\n'
                        'socket.socket.connect = blocked\n'
                        'socket.socket.connect_ex = blocked\n')
                    environment = {
                        'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin',
                        'HOME': directory, 'TMPDIR': directory,
                        'PYTHONPATH': directory, 'PYTHONDONTWRITEBYTECODE': '1',
                        # Offline operations must also tolerate unused auth proxies.
                        'https_proxy': 'http://synthetic-user:synthetic-secret@proxy.invalid:8080',
                    }
                    process = subprocess.Popen(command, cwd=resolve(server.get('cwd', str(ROOT))),
                        env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stdout, selectors.EVENT_READ)
                            pending = bytearray()

                            def send(message):
                                process.stdin.write(json.dumps(message).encode() + b'\n')
                                process.stdin.flush()

                            def receive():
                                deadline = time.monotonic() + 10
                                while b'\n' not in pending:
                                    remaining = deadline - time.monotonic()
                                    self.assertGreater(remaining, 0, 'No response while stdin remained open')
                                    self.assertTrue(selector.select(remaining), 'Host command did not flush its response')
                                    chunk = os.read(process.stdout.fileno(), 65536)
                                    self.assertTrue(chunk, 'Host command exited before responding')
                                    pending.extend(chunk)
                                line, _, tail = pending.partition(b'\n')
                                pending[:] = tail
                                return json.loads(line)

                            send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                                'protocolVersion': '2025-06-18', 'capabilities': {},
                                'clientInfo': {'name': 'offline-config-test', 'version': '1'}}})
                            reply = receive()
                            self.assertEqual(reply['id'], 1)
                            self.assertEqual(reply['result']['serverInfo'], {'name': SLUG, 'version': METADATA['version']})
                            send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                            send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                                'name': SLUG.replace('-', '_') + '_demo', 'arguments': {}}})
                            reply = receive()
                            self.assertEqual(reply['id'], 2)
                            self.assertFalse(reply['result']['isError'])
                            example = reply['result']['structuredContent']['example']
                            self.assertFalse(example['live'])
                            self.assertEqual(example['mode'], 'saved_official_snapshot')
                            self.assertFalse(process.stdin.closed)
                            self.assertIsNone(process.poll())
                            self.assertNotIn('synthetic-secret', json.dumps(reply))
                    finally:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        for stream in (process.stdin, process.stdout, process.stderr):
                            stream.close()


if __name__ == '__main__':
    unittest.main()
