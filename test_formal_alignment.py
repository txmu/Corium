"""Real production regressions for properties exposed by the Lean work."""
import base64
import copy
from contextlib import closing
import hashlib
import json
import shlex
import sqlite3
import unittest

from test_core import Fixture


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def root_of(leaves):
    level = list(leaves)
    if not level:
        return hashlib.sha256(b'').hexdigest()
    while len(level) > 1:
        level = [hashlib.sha256((level[i] + level[min(i + 1, len(level) - 1)]).encode()).hexdigest()
                 for i in range(0, len(level), 2)]
    return level[0]


class FormalAlignmentTests(Fixture):
    def codec(self, mode, *args, ok=True):
        return self.run_core('_internal_ibc_codec ' + ' '.join(shlex.quote(str(x)) for x in (mode, *args)), ok)

    def dispatch_block(self, destination='default'):
        data = {'target_chain_id': destination, 'message_type': 'mail',
                'message_payload': {'body': '中文🙂', 'recipient_id': self.identity}}
        raw = compact({'type': 'ibc_dispatch', 'data': data, 'timestamp': 1})
        target = hashlib.sha256(raw.encode()).hexdigest()
        with closing(sqlite3.connect(self.chain)) as db, db:
            previous = db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
            body = compact({'height': 1, 'previous_hash': previous, 'timestamp': 1, 'transactions': [target]})
            block_hash = hashlib.sha256(body.encode()).hexdigest()
            db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)',
                       (target, 'ibc_dispatch', compact(data), self.sign(raw), self.pem, 1, 1))
            db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)',
                       (1, block_hash, previous, 1, self.identity, self.sign(body), compact([target]), 1000))
        return target, block_hash, data

    def proof(self, target):
        result = self.run_core('_internal_ibc_generate_proof ' + shlex.quote(target))
        return json.loads(result.stdout.splitlines()[-1])

    def envelope(self, target, data, proof):
        return {'source_tx_hash': target, 'message_type': data['message_type'],
                'message_payload': data['message_payload'], 'proof_data': proof}

    def verify(self, payload, anchor, ok=True):
        encoded = base64.b64encode(compact(payload).encode()).decode()
        result = self.codec('verify', encoded, anchor, 'default', ok=ok)
        return result

    def test_merkle_all_positions_odd_levels_and_duplicates(self):
        for size in range(1, 10):
            leaves = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(size)]
            for target in leaves:
                result = self.run_core('_internal_generate_merkle_siblings ' + ' '.join([target, *leaves]))
                path = json.loads(result.stdout.splitlines()[-1])
                self.run_core('_internal_verify_merkle_proof ' + shlex.quote(compact({'transactions_root': root_of(leaves)}))
                              + ' ' + shlex.quote(compact({'target_tx_hash': target, 'siblings': path})))
        leaves = ['a' * 64, 'b' * 64, 'a' * 64]
        path = json.loads(self.codec('siblings', leaves[0], *leaves).stdout.splitlines()[-1])
        self.codec('merkle', compact({'transactions_root': root_of(leaves)}),
                   compact({'target_tx_hash': leaves[0], 'siblings': path}))

    def test_merkle_absent_target_empty_singleton_and_invalid_leaves(self):
        for leaves in ([], ['a' * 64], ['a' * 64, 'b' * 64], ['bad']):
            self.run_core('_internal_generate_merkle_siblings ' + ' '.join(['f' * 64, *leaves]), ok=False)

    def test_merkle_malformed_proof_never_accepted(self):
        valid = {'target_tx_hash': 'a' * 64, 'siblings': []}
        for header, proof in (({}, {}), ({'transactions_root': None}, valid),
                              ({'transactions_root': 'a' * 64}, {'target_tx_hash': 'a' * 64, 'siblings': {}}),
                              ({'transactions_root': 'a' * 64}, {'target_tx_hash': 'a' * 64,
                               'siblings': [{'hash': 'b' * 64, 'position': 'unknown'}]})):
            self.codec('merkle', compact(header), compact(proof), ok=False)
        self.codec('merkle', '{"transactions_root":"'+'a'*64+'"}',
                   '{"target_tx_hash":"'+'a'*64+'","siblings":[],"siblings":[]}', ok=False)

    def test_checkpoint_roundtrip_and_anchor_is_not_advanced(self):
        target, block_hash, data = self.dispatch_block()
        checkpoint = self.add_empty_block(2, block_hash)
        proof = self.proof(target)
        self.assertEqual(proof['final_header']['transactions_root'], target)
        self.assertNotEqual(proof['final_header']['hash'], target)
        payload = self.envelope(target, data, proof)
        self.verify(payload, checkpoint)
        reordered = copy.deepcopy(payload)
        reordered['message_payload'] = dict(reversed(list(reordered['message_payload'].items())))
        self.verify(reordered, checkpoint)
        # A trusted final block is sufficient; no extra headers are needed.
        direct = copy.deepcopy(payload)
        direct['proof_data']['header_chain'] = []
        self.verify(direct, block_hash)
        with closing(sqlite3.connect(self.chain)) as db, db:
            db.execute('INSERT INTO ibc_verifiers VALUES (?,?,?,?,?)',
                       ('foreign', 'BUILT_IN:hash-chain-v1', 1, checkpoint, 0))
        encoded = base64.b64encode(compact(payload).encode()).decode()
        self.run_core('_internal_verify_hash_chain_proof foreign ' + shlex.quote(encoded))
        with closing(sqlite3.connect(self.chain)) as db, db:
            self.assertEqual(db.execute('SELECT last_known_header_hash FROM ibc_verifiers').fetchone()[0], checkpoint)

    def test_old_anchor_does_not_authenticate_fabricated_descendants(self):
        target, _, data = self.dispatch_block()
        proof = self.proof(target)
        with closing(sqlite3.connect(self.chain)) as db, db:
            old_anchor = db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        self.verify(self.envelope(target, data, proof), old_anchor, ok=False)

    def test_committed_message_destination_and_hash_bindings(self):
        target, block_hash, data = self.dispatch_block()
        original = self.envelope(target, data, self.proof(target))
        for change in (
            lambda p: p.update(message_type='other'),
            lambda p: p.update(message_payload={'body': 'forged'}),
            lambda p: p.update(source_tx_hash='f' * 64),
            lambda p: p['proof_data'].update(source_transaction='{}'),
            lambda p: p['proof_data']['final_header'].update(transactions_root='f' * 64),
            lambda p: p['proof_data']['final_header'].update(transactions=['f' * 64]),
            lambda p: p['proof_data'].update(format='legacy'),
        ):
            payload = copy.deepcopy(original)
            change(payload)
            self.verify(payload, block_hash, ok=False)
        self.codec('verify', base64.b64encode(compact(original).encode()).decode(), block_hash, 'other-chain', ok=False)

    def test_checkpoint_chain_gaps_and_reordered_headers_rejected(self):
        target, block_hash, data = self.dispatch_block()
        middle = self.add_empty_block(2, block_hash)
        checkpoint = self.add_empty_block(3, middle)
        original = self.envelope(target, data, self.proof(target))
        self.verify(original, checkpoint)
        for chain in ([original['proof_data']['header_chain'][0]],
                      list(reversed(original['proof_data']['header_chain']))):
            payload = copy.deepcopy(original)
            payload['proof_data']['header_chain'] = chain
            self.verify(payload, checkpoint, ok=False)

    def test_uncommitted_or_inconsistent_transaction_cannot_generate_proof(self):
        target, _, _ = self.dispatch_block()
        with closing(sqlite3.connect(self.chain)) as db, db:
            db.execute('UPDATE transactions SET block_height=NULL WHERE hash=?', (target,))
        self.run_core('_internal_ibc_generate_proof ' + target, ok=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
