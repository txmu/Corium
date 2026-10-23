"""Unit and integration tests for ConsensusValidationCore."""
import json
import copy
import os
import shutil
import sqlite3
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from consensus_core import (
    ConsensusValidationCore,
    ConsensusError,
    calculate_retarget,
    calculate_block_work,
    target_from_bits,
    bits_from_target,
    MAX_TARGET,
    MIN_TARGET,
    TARGET_SPACING,
    RETARGET_INTERVAL,
    WORK_V2_ACTIVATION_HEIGHT,
    sha256_hex
)


class TestConsensusCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='corium_test_core_')
        self.db_path = os.path.join(self.temp_dir, 'chain.db')
        self.core = ConsensusValidationCore(self.db_path, network_id='test-network-v3')
        self._init_db()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _init_db(self):
        with self.core.connection_scope() as db:
            db.execute('''
                CREATE TABLE blocks (
                    height INTEGER PRIMARY KEY,
                    hash TEXT UNIQUE NOT NULL,
                    previous_hash TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    validator TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    transactions TEXT NOT NULL,
                    total_weight INTEGER DEFAULT 0
                )
            ''')
            db.execute('CREATE TABLE block_work (hash TEXT PRIMARY KEY, proof TEXT NOT NULL)')
            db.execute('CREATE TABLE system_params (param_key TEXT PRIMARY KEY, param_value TEXT NOT NULL)')
            db.execute('CREATE TABLE validators (public_key TEXT PRIMARY KEY, public_key_hash TEXT UNIQUE, stake INTEGER NOT NULL, status TEXT)')

            # Insert genesis block
            genesis_hash = '599b7512c4ffb640520433f0772f00e78198ad958f444d25459dbca8c38ce0fa'
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (0, ?, '0', 1000000, 'genesis_node', 'genesis_sig', '[]', 0)
            ''', (genesis_hash,))

    def test_target_bits_conversion(self):
        target_4 = target_from_bits(4)
        self.assertGreater(target_4, 0)
        self.assertEqual(bits_from_target(target_4), 4)

        target_16 = target_from_bits(16)
        self.assertLess(target_16, target_4)
        self.assertEqual(bits_from_target(target_16), 16)

    def test_calculate_block_work(self):
        target_low = target_from_bits(4)
        target_high = target_from_bits(16)
        work_low = calculate_block_work(target_low)
        work_high = calculate_block_work(target_high)

        self.assertGreater(work_high, work_low)
        self.assertGreater(work_low, 0)
        self.assertIsInstance(work_low, int)
        self.assertIsInstance(work_high, int)

    def test_deterministic_retarget_damping(self):
        expected_window = RETARGET_INTERVAL * TARGET_SPACING # 600s
        initial_target = target_from_bits(8)

        # 1. Faster blocks (e.g. 100s instead of 600s) -> target must decrease (difficulty increases)
        fast_target = calculate_retarget(initial_target, 100, expected_window)
        self.assertLess(fast_target, initial_target)

        # 2. Slower blocks (e.g. 1200s instead of 600s) -> target must increase (difficulty decreases)
        slow_target = calculate_retarget(initial_target, 1200, expected_window)
        self.assertGreater(slow_target, initial_target)

        # 3. Damping limits: timespan clamped to [600//4, 600*4] = [150, 2400]
        # Extremely fast: 10s should behave the same as 150s
        extremely_fast = calculate_retarget(initial_target, 10, expected_window)
        clamped_fast = calculate_retarget(initial_target, 150, expected_window)
        self.assertEqual(extremely_fast, clamped_fast)

        # Extremely slow: 10000s should behave the same as 2400s
        extremely_slow = calculate_retarget(initial_target, 10000, expected_window)
        clamped_slow = calculate_retarget(initial_target, 2400, expected_window)
        self.assertEqual(extremely_slow, clamped_slow)

    def test_mine_and_verify_unstaked_miner(self):
        # Generate an unstaked keypair (not in validators table)
        priv_key = ec.generate_private_key(ec.SECP256K1())
        priv_pem = priv_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()
        )

        # Mine block 1
        genesis = self.core.get_block_by_height(0)
        res = self.core.mine_candidate_block(
            private_key_pem=priv_pem,
            parent_hash=genesis['hash'],
            timestamp=genesis['timestamp'] + 60,
            transactions=[],
            attempts=100000
        )

        self.assertTrue(res['verified'])
        self.assertEqual(res['height'], 1)
        self.assertEqual(res['block']['previous_hash'], genesis['hash'])
        self.assertGreater(res['total_weight'], genesis['total_weight'])

        # Store block in db to simulate committing it
        with self.core.get_connection() as db:
            b = res['block']
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (b['height'], res['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res['total_weight']))
            db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res['hash'], json.dumps(b['work'])))

        # Verify through verify_block_integrity
        stored = self.core.get_block_by_hash(res['hash'])
        verification = self.core.verify_block_integrity(stored, res['hash'])
        self.assertTrue(verification['verified'])

    def test_forged_signature_rejected(self):
        priv_key1 = ec.generate_private_key(ec.SECP256K1())
        priv_pem1 = priv_key1.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        priv_key2 = ec.generate_private_key(ec.SECP256K1())

        genesis = self.core.get_block_by_height(0)
        res = self.core.mine_candidate_block(
            private_key_pem=priv_pem1,
            parent_hash=genesis['hash'],
            timestamp=genesis['timestamp'] + 60,
            transactions=[],
            attempts=100000
        )

        # Forge signature using priv_key2
        forged_block = dict(res['block'])
        raw_bytes = self.core.signing_bytes(forged_block)
        forged_block['signature'] = priv_key2.sign(raw_bytes, ec.ECDSA(hashes.SHA256())).hex()

        with self.assertRaises(ConsensusError) as cm:
            self.core.verify_block_integrity(forged_block, res['hash'])
        self.assertIn('INVALID_SIGNATURE', str(cm.exception))

    def test_low_work_fork_cannot_claim_high_weight(self):
        key = ec.generate_private_key(ec.SECP256K1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        genesis = self.core.get_block_by_height(0)
        honest = self.core.mine_candidate_block(pem, genesis['hash'], genesis['timestamp'] + 60, [])
        target = honest['target']
        honest_tip = {'hash': 'f' * 64, 'total_weight': 2 * calculate_block_work(target)}

        # Re-mine the changed body at the network's EASY target, then sign it
        # with the legitimate miner key. Rejection must not rely on stale PoW/signatures.
        for claimed in (1, target + 1, str(target), True, None, 'absent'):
            with self.subTest(claimed=claimed):
                block = copy.deepcopy(honest['block'])
                if claimed == 'absent':
                    del block['work']['target']
                else:
                    block['work']['target'] = claimed
                context = self.core.work_context(block)
                for nonce in range(100000):
                    digest = self.core.calculate_work_digest(block['work']['policy'], context, nonce)
                    if 1 < int(digest, 16) <= target:
                        break
                else:
                    self.fail('Could not mine adversarial test block')
                block['work']['nonce'] = nonce
                raw = self.core.signing_bytes(block)
                block['signature'] = key.sign(raw, ec.ECDSA(hashes.SHA256())).hex()
                self.assertTrue(self.core.verify_miner_signature(block, raw))
                identity = sha256_hex(raw)
                if claimed == 'absent':
                    result = self.core.verify_block_integrity(block, identity)
                    self.assertEqual(result['block_work'], calculate_block_work(target))
                    self.assertFalse(self.core.should_reorganize(result, honest_tip))
                else:
                    with self.assertRaises(ConsensusError) as failure:
                        self.core.verify_block_integrity(block, identity)
                    self.assertEqual(failure.exception.code, 'TARGET_MISMATCH')

    def test_fork_choice_rule(self):
        # Tip A at height 1 with weight 1000, Tip B at height 2 with weight 2000
        with self.core.get_connection() as db:
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (1, 'aaaa', '0', 1000060, 'val_a', 'sig_a', '[]', 1000)
            ''')
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (2, 'bbbb', 'aaaa', 1000120, 'val_b', 'sig_b', '[]', 2000)
            ''')

        # Candidate 'bbbb' (weight 2000) vs Current 'aaaa' (weight 1000) -> True
        self.assertTrue(self.core.should_reorganize('bbbb', 'aaaa'))
        # Candidate 'aaaa' (weight 1000) vs Current 'bbbb' (weight 2000) -> False
        self.assertFalse(self.core.should_reorganize('aaaa', 'bbbb'))

        # Tie-breaker when weights are equal: lexicographical hash
        # '0000_hash' < '1111_hash' -> True
        with self.core.get_connection() as db:
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (3, '0000_hash', 'aaaa', 1000180, 'val_a', 'sig_a', '[]', 3000)
            ''')
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (4, '1111_hash', 'aaaa', 1000180, 'val_b', 'sig_b', '[]', 3000)
            ''')
        # Candidate '0000_hash' vs Current '1111_hash' -> True (lower hash wins tie)
        self.assertTrue(self.core.should_reorganize('0000_hash', '1111_hash'))
        # Candidate '1111_hash' vs Current '0000_hash' -> False
        self.assertFalse(self.core.should_reorganize('1111_hash', '0000_hash'))

    def test_invalid_timestamp_rejected(self):
        priv_key = ec.generate_private_key(ec.SECP256K1())
        priv_pem = priv_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        genesis = self.core.get_block_by_height(0)

        # 1. Past timestamp (< parent timestamp)
        with self.assertRaises(ConsensusError) as cm:
            self.core.mine_candidate_block(
                private_key_pem=priv_pem,
                parent_hash=genesis['hash'],
                timestamp=genesis['timestamp'] - 10,
                transactions=[]
            )
        self.assertIn('TIMESTAMP_DECREASING', str(cm.exception))

    def test_duplicate_transaction_rejected(self):
        priv_key = ec.generate_private_key(ec.SECP256K1())
        priv_pem = priv_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        genesis = self.core.get_block_by_height(0)
        dup_tx = 'a' * 64

        with self.assertRaises(ConsensusError) as cm:
            self.core.mine_candidate_block(
                private_key_pem=priv_pem,
                parent_hash=genesis['hash'],
                timestamp=genesis['timestamp'] + 60,
                transactions=[dup_tx, dup_tx]
            )
        self.assertIn('DUPLICATE_TX', str(cm.exception))

    def test_multi_block_dynamic_retargeting_simulation(self):
        priv_key = ec.generate_private_key(ec.SECP256K1())
        priv_pem = priv_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )

        with self.core.connection_scope() as db:
            db.execute("INSERT OR REPLACE INTO system_params VALUES ('dynamic_pow_activation_height', '1')")

        tip = self.core.get_block_by_height(0)
        initial_target = self.core.get_expected_target(tip['height'], tip['hash'], tip['timestamp'])

        # Mine 10 fast blocks (spacing 10s instead of 60s)
        for h in range(1, 11):
            block_time = tip['timestamp'] + 10
            res = self.core.mine_candidate_block(
                private_key_pem=priv_pem,
                parent_hash=tip['hash'],
                timestamp=block_time,
                transactions=[],
                attempts=100000
            )
            b = res['block']
            with self.core.connection_scope() as db:
                db.execute('''
                    INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (b['height'], res['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res['total_weight']))
                db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res['hash'], json.dumps(b['work'])))
            tip = self.core.get_block_by_height(h)

        # At block 11, target should have retargeted to a lower target (higher difficulty)
        next_target = self.core.get_expected_target(tip['height'], tip['hash'], tip['timestamp'])
        self.assertLess(next_target, initial_target)
        self.assertGreaterEqual(bits_from_target(next_target), bits_from_target(initial_target))

        # Persisted miner metadata must not control future difficulty. This also
        # covers old accepted proofs with target omitted after a retarget boundary.
        with self.core.connection_scope() as db:
            proof = json.loads(db.execute('SELECT proof FROM block_work WHERE hash=?', (tip['hash'],)).fetchone()[0])
            for claimed in (1, None):
                if claimed is None:
                    proof.pop('target', None)
                else:
                    proof['target'] = claimed
                db.execute('UPDATE block_work SET proof=? WHERE hash=?', (json.dumps(proof), tip['hash']))
                # get_expected_target uses a different reader, so commit each fixture mutation.
                db.commit()
                self.assertEqual(self.core.get_expected_target(tip['height'], tip['hash'], tip['timestamp']), next_target)


if __name__ == '__main__':
    unittest.main()
