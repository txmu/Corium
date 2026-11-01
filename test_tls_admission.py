"""Real TLS and native signed PING through the production bounded server."""
import ast
import http.client
import json
import socket
import ssl
import subprocess
import threading
import time
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
import test_gateway as fixtures


class TLSAdmissionTests(unittest.TestCase):
    def setUp(self):
        fixtures.GatewayTests.setUp(self)
        factory = next(n for n in ast.walk(ast.parse(fixtures.DAEMON))
                       if isinstance(n, ast.FunctionDef) and n.name == 'create_server')
        exec(compile(ast.Module(body=[factory], type_ignores=[]),
                     'native-create-server', 'exec'), self.ns)
        cert, key = self.root/'tls.crt', self.root/'tls.key'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                        '-nodes', '-keyout', str(key), '-out', str(cert),
                        '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=IP:127.0.0.1'],
                       check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.client_context = ssl.create_default_context(cafile=str(cert))
        self.server = self.ns['create_server'](
            0, self.ns['CoriumGatewayHandler'], context)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.idle = []
        self.addCleanup(lambda: [connection.close() for connection in self.idle])

    def ping(self):
        packet = dict(type='PING', payload='', sender_id=self.identity,
                      public_key=self.pem,
                      signature=self.key.sign(b'PING|', ec.ECDSA(hashes.SHA256())).hex())
        connection = http.client.HTTPSConnection(
            '127.0.0.1', self.server.server_port,
            context=self.client_context, timeout=2)
        try:
            connection.request('POST', '/dht', json.dumps(packet),
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()),
                             {'status': 'success', 'data': 'PONG:'+self.identity})
        finally:
            connection.close()

    def connect_idle(self, count):
        for _ in range(count):
            self.idle.append(socket.create_connection(
                ('127.0.0.1', self.server.server_port), timeout=2))

    def test_half_open_tls_does_not_block_signed_ping(self):
        self.connect_idle(8)
        self.idle[0].sendall(b'\x16\x03')  # Incomplete TLS record, real TCP.
        self.ping()
        # Malformed clients are isolated too; neither disables TLS verification.
        self.idle[1].sendall(b'GET / HTTP/1.0\r\n\r\n')
        self.ping()

    def test_worker_budget_and_handshake_timeout_recover_capacity(self):
        self.connect_idle(64)
        deadline = time.monotonic()+2
        while self.server.worker_slots._value and time.monotonic()<deadline:
            time.sleep(.02)
        self.assertEqual(self.server.worker_slots._value, 0)
        # A connection above the fixed budget is closed, not queued in a worker.
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2) as extra:
            self.assertEqual(extra.recv(1), b'')
        deadline = time.monotonic()+7
        while self.server.worker_slots._value != 64 and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertEqual(self.server.worker_slots._value, 64)
        self.ping()


if __name__ == '__main__':
    unittest.main()
