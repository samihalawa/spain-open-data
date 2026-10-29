"""Proxy routing/security regressions; synthetic configuration, no network."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import ssl
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SLUG = json.loads((ROOT / 'plugin.json').read_text())['name']
sys.path.insert(0, str(ROOT / 'skills' / SLUG / 'scripts'))
from spain_suite import core as c

URL = 'https://www.boe.es/test'


class TransportReached(Exception):
    pass


class ProxyPolicy(unittest.TestCase):
    def configured(self, env):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        # Platform proxy settings must not enter these synthetic tests.
        stack.enter_context(patch.object(urllib.request, 'getproxies', urllib.request.getproxies_environment))
        stack.enter_context(patch.object(urllib.request, 'proxy_bypass', urllib.request.proxy_bypass_environment))
        transport = stack.enter_context(patch.object(urllib.request.HTTPSHandler, 'do_open', side_effect=TransportReached))
        stack.enter_context(patch('socket.create_connection', side_effect=AssertionError('Network forbidden')))
        return c.OfficialClient(), transport

    def test_authenticated_proxy_rejected_before_transport(self):
        for proxy in ('http://synthetic-user:synthetic-secret@proxy.invalid:8080',
                      'synthetic-user:synthetic-secret@proxy.invalid:8080',
                      'http://synthetic-user/slash:synthetic-secret@proxy.invalid:8080',
                      'http://synthetic-user@proxy.invalid:8080',
                      'http://:synthetic-secret@proxy.invalid:8080'):
            with self.subTest(proxy=proxy):
                client, transport = self.configured({'https_proxy': proxy})
                with self.assertRaises(c.SourceError) as caught:
                    client.get(URL)
                self.assertEqual(caught.exception.code, 'proxy_credentials_blocked')
                self.assertNotIn('synthetic-user', str(caught.exception))
                self.assertNotIn('synthetic-secret', str(caught.exception))
                self.assertIsNone(caught.exception.source_url)
                transport.assert_not_called()

    def test_unauthenticated_proxy_is_selected(self):
        client, transport = self.configured({'https_proxy': 'http://proxy.invalid:8080'})
        with self.assertRaises(TransportReached):
            client.get(URL)
        request = transport.call_args.args[1]
        self.assertEqual(request.host, 'proxy.invalid:8080')
        self.assertEqual(request._tunnel_host, 'www.boe.es')
        self.assertFalse(request.has_header('Proxy-Authorization'))

    def test_bypass_preserves_direct_routing(self):
        client, transport = self.configured({'https_proxy': 'http://synthetic-user:synthetic-secret@proxy.invalid:8080', 'no_proxy': 'www.boe.es'})
        with self.assertRaises(TransportReached):
            client.get(URL)
        request = transport.call_args.args[1]
        self.assertEqual(request.host, 'www.boe.es')
        self.assertIsNone(request._tunnel_host)
        self.assertFalse(request.has_header('Proxy-Authorization'))

    def test_no_proxy_config_preserves_direct_routing(self):
        client, transport = self.configured({})
        with self.assertRaises(TransportReached):
            client.get(URL)
        self.assertEqual(transport.call_args.args[1].host, 'www.boe.es')

    def test_source_and_redirect_allowlist_still_enforced(self):
        client, transport = self.configured({})
        for url in ('http://www.boe.es/test', 'https://outside.invalid/test', 'https://user:pass@www.boe.es/test'):
            with self.subTest(url=url), self.assertRaises(c.SourceError):
                client.get(url)
        redirect = next(h for h in client.opener.handlers if isinstance(h, c._SafeRedirect))
        with self.assertRaises(c.SourceError):
            redirect.redirect_request(urllib.request.Request(URL), None, 302, 'Moved', {}, 'https://outside.invalid/test')
        transport.assert_not_called()

    def test_tls_verification_failure_is_not_retried_or_ignored(self):
        client, transport = self.configured({'https_proxy': 'http://proxy.invalid:8080'})
        transport.side_effect = urllib.error.URLError(ssl.SSLCertVerificationError('synthetic TLS failure'))
        with self.assertRaises(c.SourceError) as caught:
            client.get(URL)
        self.assertEqual(caught.exception.code, 'source_tls_error')
        self.assertEqual(transport.call_count, 1)
        # The stock verified HTTPS handler/connection remain in the opener.
        self.assertIs(transport.call_args.args[0], c.urllib.request.http.client.HTTPSConnection)
        self.assertIsNone(transport.call_args.kwargs['context'])


if __name__ == '__main__':
    unittest.main()
