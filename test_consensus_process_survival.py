"""Lightweight local process experiment, NOT native Corium P2P or public discovery.

Each node owns its key, SQLite file and HTTP listener. Only empty transaction
blocks are supported: this checks consensus history, not application-state replay.
"""
import json
import copy
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec

from consensus_core import ConsensusValidationCore, MAINNET_GENESIS_HASH, sha256_hex, target_from_bits


def rpc(address, method, value=None):
    data = None if value is None else json.dumps(value).encode()
    with urlopen(Request(address + method, data=data,
                         headers={'Content-Type': 'application/json'}), timeout=5) as response:
        return json.load(response)


def node_process(path, ready):
    core = ConsensusValidationCore(path, 'test-process-survival')
    key = ec.generate_private_key(ec.SECP256K1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    with core.connection_scope() as db:
        db.execute('CREATE TABLE blocks (height INTEGER PRIMARY KEY, hash TEXT UNIQUE, '
                   'previous_hash TEXT, timestamp INTEGER, validator TEXT, signature TEXT, '
                   'transactions TEXT, total_weight INTEGER)')
        db.execute('CREATE TABLE block_work (hash TEXT PRIMARY KEY, proof TEXT)')
        db.execute('CREATE TABLE system_params (param_key TEXT PRIMARY KEY, param_value TEXT)')
        db.execute('CREATE TABLE validators (public_key_hash TEXT PRIMARY KEY, stake INTEGER)')
        db.execute('INSERT INTO blocks VALUES (0,?,\'0\',1000000,\'genesis\',\'\',\'[]\',0)',
                   (MAINNET_GENESIS_HASH,))

    def accept(block):
        # Wire weights are discarded; every receiver recomputes from its own prefix.
        checked = core.verify_block_integrity(block, block['hash'])
        with core.connection_scope() as db:
            db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)',
                       (block['height'], block['hash'], block['previous_hash'], block['timestamp'],
                        block['validator'], block['signature'], json.dumps(block['transactions']),
                        checked['total_weight']))
            db.execute('INSERT INTO block_work VALUES (?,?)',
                       (block['hash'], json.dumps(block['work'])))
        return checked

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_rpc(None)

        def do_POST(self):
            self.handle_rpc(json.loads(self.rfile.read(int(self.headers['Content-Length']))))

        def handle_rpc(self, value):
            try:
                if self.path == '/blocks':
                    result = [core.get_block_by_height(h) for h in range(1, core.get_tip()['height'] + 1)]
                elif self.path == '/status':
                    with core.connection_scope() as db:
                        miners = db.execute('SELECT COUNT(*) FROM validators').fetchone()[0]
                    result = {'tip': core.get_tip(), 'registered_validators': miners}
                elif self.path == '/mine':
                    tip = core.get_tip()
                    result = core.mine_candidate_block(pem, tip['hash'], tip['timestamp'] + 60, [])
                    accept({**result['block'], 'hash': result['hash']})
                elif self.path == '/accept':
                    result = accept(value)
                elif self.path == '/sync':
                    for block in rpc(value['peer'], '/blocks'):
                        if block['height'] > core.get_tip()['height']:
                            accept(block)
                        elif core.get_block_by_height(block['height'])['hash'] != block['hash']:
                            raise ValueError('Divergent prefix requires separately validated fork choice')
                    result = core.get_tip()
                else:
                    raise ValueError('Unknown test endpoint')
                status = 200
            except Exception as exc:
                result, status = {'error': str(exc)}, 400
            body = json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(('127.0.0.1', 0), Handler)
    ready.send('http://127.0.0.1:' + str(server.server_port))
    ready.close()
    server.serve_forever()


class ProcessSurvivalTests(unittest.TestCase):
    def test_founder_process_stops_and_fresh_node_revalidates_history(self):
        context = multiprocessing.get_context('spawn')
        processes = []
        with tempfile.TemporaryDirectory(prefix='corium-process-') as directory:
            def start(index):
                reader, writer = context.Pipe(duplex=False)
                process = context.Process(target=node_process,
                                          args=(str(Path(directory) / f'{index}.db'), writer))
                process.start()
                processes.append(process)
                writer.close()
                self.assertTrue(reader.poll(10), 'Node failed to start')
                address = reader.recv()
                reader.close()
                return address

            try:
                founder, b, c = [start(index) for index in range(3)]
                rpc(founder, '/mine', {})
                for peer in (b, c):
                    rpc(peer, '/sync', {'peer': founder})
                processes[0].terminate()
                processes[0].join(5)
                self.assertFalse(processes[0].is_alive())
                rpc(b, '/mine', {})
                rpc(c, '/sync', {'peer': b})
                rpc(c, '/mine', {})
                rpc(b, '/sync', {'peer': c})
                fresh = start(3)
                self.assertEqual(rpc(fresh, '/status')['tip']['height'], 0)
                rpc(fresh, '/sync', {'peer': c})
                expected = rpc(b, '/status')['tip']
                self.assertEqual(expected['height'], 3)
                for peer in (b, c, fresh):
                    status = rpc(peer, '/status')
                    self.assertEqual(status['tip'], expected)
                    self.assertEqual(status['registered_validators'], 0)
                # A received cumulative weight is never authoritative.
                mined = rpc(b, '/mine', {})
                malicious = copy.deepcopy(mined['block'])
                key = ec.generate_private_key(ec.SECP256K1())
                public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
                malicious['work'].update(target=1, miner_public_key=public)
                malicious['validator'] = sha256_hex(public.encode())
                context_value = ConsensusValidationCore.work_context(malicious)
                for nonce in range(100000):
                    digest = ConsensusValidationCore.calculate_work_digest(malicious['work']['policy'], context_value, nonce)
                    if 1 < int(digest, 16) <= target_from_bits(4):
                        break
                else:
                    self.fail('Adversarial mining exhausted')
                malicious['work']['nonce'] = nonce
                raw = ConsensusValidationCore.signing_bytes(malicious)
                malicious['signature'] = key.sign(raw, ec.ECDSA(hashes.SHA256())).hex()
                with self.assertRaises(HTTPError) as failure:
                    rpc(fresh, '/accept', {**malicious, 'hash': sha256_hex(raw), 'total_weight': 2**255})
                self.assertEqual(failure.exception.code, 400)
                self.assertIn('TARGET_MISMATCH', failure.exception.read().decode())
                failure.exception.close()
                self.assertEqual(rpc(fresh, '/status')['tip'], expected)
                wire = {**mined['block'], 'hash': mined['hash'], 'total_weight': 2**255}
                checked = rpc(fresh, '/accept', wire)
                self.assertEqual(checked['total_weight'], mined['total_weight'])
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(5)
                    if process.is_alive():
                        process.kill()
                        process.join(5)


if __name__ == '__main__':
    unittest.main()
