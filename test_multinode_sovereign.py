"""Automated multi-node sovereign survival and unstaked miner consensus test suite.

Simulates 4 independent nodes (A: Founder, B: Independent 1, C: Independent 2, D: Fresh Node).
Executes the Core Disconnection Experiment:
1. All nodes reach identical state at genesis/tip.
2. Founder Node A is severed (isolated/killed).
3. Independent unstaked miners (stake=0, not in validators table) on Node B/C produce valid PoW blocks.
4. Independent verification and transaction inclusion by peer nodes without founder.
5. Node D boots from scratch, syncs exclusively from B/C without contacting A.
6. Reorg, partition, invalid PoW, forged signature, and attack defense tests.
"""
import copy
import json
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
    calculate_block_work,
    calculate_retarget,
    target_from_bits,
    MAINNET_GENESIS_HASH,
    WORK_V2_ACTIVATION_HEIGHT
)


class MultiNodeEnvironment:
    """Manages isolated data directories and consensus instances for multiple nodes."""

    def __init__(self, base_dir: str, network_id: str = 'test-sovereign-v3'):
        self.base_dir = base_dir
        self.network_id = network_id
        self.nodes = {}

    def create_node(self, node_name: str, copy_from: str = None) -> ConsensusValidationCore:
        node_dir = os.path.join(self.base_dir, node_name)
        os.makedirs(node_dir, exist_ok=True)
        db_path = os.path.join(node_dir, 'chain.db')

        # Generate unique key for node
        priv_key = ec.generate_private_key(ec.SECP256K1())
        priv_pem = priv_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        pub_pem = priv_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        key_file = os.path.join(node_dir, 'identity.key')
        with open(key_file, 'wb') as f:
            f.write(priv_pem)
        with open(key_file + '.pub', 'wb') as f:
            f.write(pub_pem)

        if copy_from and copy_from in self.nodes:
            src_db = self.nodes[copy_from]['db_path']
            shutil.copy2(src_db, db_path)
        else:
            db = sqlite3.connect(db_path)
            try:
                with db:
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
                    db.execute('CREATE TABLE transactions (hash TEXT PRIMARY KEY, type TEXT, data TEXT, signature TEXT, public_key TEXT, timestamp INTEGER, block_height INTEGER)')
                    db.execute('CREATE TABLE validators (public_key TEXT PRIMARY KEY, public_key_hash TEXT UNIQUE, stake INTEGER NOT NULL, status TEXT)')
            finally:
                db.close()

        core = ConsensusValidationCore(db_path, self.network_id)
        self.nodes[node_name] = {
            'dir': node_dir,
            'db_path': db_path,
            'key_file': key_file,
            'priv_pem': priv_pem,
            'pub_pem': pub_pem,
            'core': core,
            'online': True
        }
        return core

    def isolate_node(self, node_name: str):
        """Sever node from network (simulate crash / DNS cut / gateway kill)."""
        if node_name in self.nodes:
            self.nodes[node_name]['online'] = False

    def is_online(self, node_name: str) -> bool:
        return self.nodes.get(node_name, {}).get('online', False)

    def sync_blocks(self, from_node: str, to_node: str) -> int:
        """Sync blocks from one node to another using ConsensusValidationCore."""
        if not self.is_online(from_node) or not self.is_online(to_node):
            raise RuntimeError(f'Cannot sync: one or both nodes are offline ({from_node}->{to_node})')

        src_core = self.nodes[from_node]['core']
        dst_core = self.nodes[to_node]['core']

        src_tip = src_core.get_tip()
        dst_tip = dst_core.get_tip()

        start_h = (dst_tip['height'] + 1) if dst_tip else 0
        end_h = src_tip['height'] if src_tip else -1

        applied = 0
        for h in range(start_h, end_h + 1):
            block = src_core.get_block_by_height(h)
            if not block:
                break
            # Validate block via dst_core
            verification = dst_core.verify_block_integrity(block, block['hash'])
            assert verification['verified']

            # Commit to dst db
            with dst_core.connection_scope() as db:
                b = block
                tx_json = json.dumps(b['transactions']) if isinstance(b['transactions'], list) else b['transactions']
                db.execute('''
                    INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (b['height'], b['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], tx_json, verification['total_weight']))
                if 'work' in b:
                    db.execute('INSERT OR REPLACE INTO block_work (hash, proof) VALUES (?, ?)', (b['hash'], json.dumps(b['work'])))
            applied += 1

        return applied


class TestMultiNodeSovereignSurvival(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix='ziokt_multinode_test_')
        self.env = MultiNodeEnvironment(self.temp_root)

        # 1. Setup Node A (Founder Node) with Genesis
        self.core_a = self.env.create_node('Node_A')
        with self.core_a.connection_scope() as db:
            genesis_hash = MAINNET_GENESIS_HASH
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (0, ?, '0', 1700000000, 'founder_node', 'founder_sig', '[]', 0)
            ''', (genesis_hash,))
            db.execute("INSERT INTO system_params VALUES ('dynamic_pow_activation_height', '1')")

        # Mine 5 blocks on Node A to establish common history
        priv_a = self.env.nodes['Node_A']['priv_pem']
        tip = self.core_a.get_block_by_height(0)
        for h in range(1, 6):
            res = self.core_a.mine_candidate_block(priv_a, tip['hash'], tip['timestamp'] + 60, [])
            b = res['block']
            with self.core_a.connection_scope() as db:
                db.execute('''
                    INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (b['height'], res['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res['total_weight']))
                db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res['hash'], json.dumps(b['work'])))
            tip = self.core_a.get_block_by_height(h)

        # 2. Setup Node B and Node C as independent full nodes synced with A
        self.core_b = self.env.create_node('Node_B', copy_from='Node_A')
        self.core_c = self.env.create_node('Node_C', copy_from='Node_A')

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_core_disconnection_and_unstaked_survival(self):
        """Core Experiment:
        1. Verify A, B, C start with identical tip.
        2. Verify B and C operators have 0 stake and do NOT exist in validators table.
        3. Completely sever Founder Node A.
        4. Node B produces valid PoW block with a real user transaction.
        5. Node C independently receives, validates, and accepts the block.
        6. Node C produces the subsequent PoW block; Node B validates and accepts.
        7. Fresh Node D joins with empty DB, connects only to B & C, and syncs to tip.
        """
        tip_a = self.core_a.get_tip()
        tip_b = self.core_b.get_tip()
        tip_c = self.core_c.get_tip()

        self.assertEqual(tip_a['hash'], tip_b['hash'])
        self.assertEqual(tip_b['hash'], tip_c['hash'])
        self.assertEqual(tip_b['height'], 5)

        # Check Node B and C are UNSTAKED: validators table is empty
        with self.core_b.connection_scope() as db:
            validators_count = db.execute('SELECT COUNT(*) FROM validators').fetchone()[0]
            self.assertEqual(validators_count, 0, 'Node B must have 0 registered validators')

        with self.core_c.connection_scope() as db:
            validators_count = db.execute('SELECT COUNT(*) FROM validators').fetchone()[0]
            self.assertEqual(validators_count, 0, 'Node C must have 0 registered validators')

        # 3. SEVER NODE A COMPLETELY
        print('[TEST] Severing Founder Node A from network...')
        self.env.isolate_node('Node_A')
        self.assertFalse(self.env.is_online('Node_A'))

        # Ensure attempting to communicate with Node A fails
        with self.assertRaises(RuntimeError):
            self.env.sync_blocks('Node_A', 'Node_B')

        # 4. Node B (unstaked miner) mines Block 6 with a valid transaction
        tx_hash = '1' * 64
        priv_b = self.env.nodes['Node_B']['priv_pem']
        tip_b = self.core_b.get_tip()

        res_b = self.core_b.mine_candidate_block(
            private_key_pem=priv_b,
            parent_hash=tip_b['hash'],
            timestamp=tip_b['timestamp'] + 60,
            transactions=[tx_hash],
            attempts=100000
        )
        self.assertTrue(res_b['verified'])
        self.assertEqual(res_b['height'], 6)

        # Commit Block 6 on Node B
        with self.core_b.connection_scope() as db:
            b = res_b['block']
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (b['height'], res_b['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res_b['total_weight']))
            db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res_b['hash'], json.dumps(b['work'])))

        # 5. Node C independently syncs Block 6 from Node B (WITHOUT Node A)
        applied = self.env.sync_blocks('Node_B', 'Node_C')
        self.assertEqual(applied, 1)

        tip_c = self.core_c.get_tip()
        self.assertEqual(tip_c['hash'], res_b['hash'])
        self.assertEqual(tip_c['height'], 6)

        # 6. Node C (another unstaked miner) mines Block 7
        priv_c = self.env.nodes['Node_C']['priv_pem']
        res_c = self.core_c.mine_candidate_block(
            private_key_pem=priv_c,
            parent_hash=tip_c['hash'],
            timestamp=tip_c['timestamp'] + 60,
            transactions=[],
            attempts=100000
        )
        with self.core_c.connection_scope() as db:
            b = res_c['block']
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (b['height'], res_c['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res_c['total_weight']))
            db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res_c['hash'], json.dumps(b['work'])))

        # Node B syncs Block 7 from Node C
        applied_b = self.env.sync_blocks('Node_C', 'Node_B')
        self.assertEqual(applied_b, 1)
        self.assertEqual(self.core_b.get_tip()['hash'], res_c['hash'])

        # 7. Node D (Fresh join node with empty database) boots and syncs from Node B (never touching A)
        print('[TEST] Booting Fresh Node D from scratch...')
        self.core_d = self.env.create_node('Node_D') # Fresh empty DB
        # Seed only genesis on Node D
        with self.core_d.connection_scope() as db:
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (0, ?, '0', 1700000000, 'founder_node', 'founder_sig', '[]', 0)
            ''', (MAINNET_GENESIS_HASH,))
            db.execute("INSERT INTO system_params VALUES ('dynamic_pow_activation_height', '1')")

        # Sync all blocks from Node B to Node D
        synced_count = self.env.sync_blocks('Node_B', 'Node_D')
        self.assertEqual(synced_count, 7) # Blocks 1 through 7

        tip_d = self.core_d.get_tip()
        self.assertEqual(tip_d['height'], 7)
        self.assertEqual(tip_d['hash'], self.core_b.get_tip()['hash'])
        self.assertEqual(tip_d['total_weight'], self.core_b.get_tip()['total_weight'])
        print('[SUCCESS] Node D fully converged with Node B & C without touching Node A!')

    def test_byzantine_and_malicious_block_defense(self):
        """Test rejection of forged, tampered, replay, and malformed blocks."""
        priv_b = self.env.nodes['Node_B']['priv_pem']
        tip_b = self.core_b.get_tip()

        # 1. Tampered transaction in valid PoW block
        res = self.core_b.mine_candidate_block(priv_b, tip_b['hash'], tip_b['timestamp'] + 60, ['2' * 64])
        tampered_block = dict(res['block'])
        tampered_block['transactions'] = ['3' * 64] # Mutated!
        with self.assertRaises(ConsensusError):
            self.core_c.verify_block_integrity(tampered_block, res['hash'])

        # 2. Forged signature
        attacker_priv = ec.generate_private_key(ec.SECP256K1())
        raw_bytes = self.core_b.signing_bytes(res['block'])
        forged_sig = attacker_priv.sign(raw_bytes, ec.ECDSA(hashes.SHA256())).hex()
        forged_block = dict(res['block'])
        forged_block['signature'] = forged_sig
        with self.assertRaises(ConsensusError) as cm:
            self.core_c.verify_block_integrity(forged_block, res['hash'])
        self.assertIn('INVALID_SIGNATURE', str(cm.exception))

        # 3. Invalid PoW nonce
        bad_pow_block = dict(res['block'])
        bad_pow_block['work'] = dict(bad_pow_block['work'])
        bad_pow_block['work']['nonce'] = (bad_pow_block['work']['nonce'] + 999999) % (2**64)
        # Changing a nonce can accidentally find another valid low-difficulty
        # proof. Select a demonstrably insufficient digest before testing admission.
        target=self.core_b.get_expected_target(tip_b['height'],tip_b['hash'],tip_b['timestamp'])
        context=self.core_b.work_context(bad_pow_block)
        for _ in range(256):
            candidate=self.core_b.calculate_work_digest(bad_pow_block['work']['policy'],context,bad_pow_block['work']['nonce'])
            if int(candidate,16)>target:break
            bad_pow_block['work']['nonce']=(bad_pow_block['work']['nonce']+1)%(2**64)
        else:self.fail('could not construct an insufficient PoW test vector')
        self.assertGreater(int(candidate,16),target)
        raw_bad = self.core_b.signing_bytes(bad_pow_block)
        bad_hash = hashes.Hash(hashes.SHA256())
        bad_hash.update(raw_bad)
        bad_hash_hex = bad_hash.finalize().hex()
        priv_key_obj = serialization.load_pem_private_key(priv_b, password=None)
        bad_pow_block['signature'] = priv_key_obj.sign(raw_bad, ec.ECDSA(hashes.SHA256())).hex()
        with self.assertRaises(ConsensusError) as cm:
            self.core_c.verify_block_integrity(bad_pow_block, bad_hash_hex)
        self.assertIn('POW_INSUFFICIENT', str(cm.exception))

        # 4. Decreasing timestamp
        bad_time_res = self.core_b.mine_candidate_block(priv_b, tip_b['hash'], tip_b['timestamp'] + 60, [])
        bad_time_block = dict(bad_time_res['block'])
        bad_time_block['timestamp'] = tip_b['timestamp'] - 100
        raw_time = self.core_b.signing_bytes(bad_time_block)
        time_hash = hashes.Hash(hashes.SHA256())
        time_hash.update(raw_time)
        time_hash_hex = time_hash.finalize().hex()
        bad_time_block['signature'] = priv_key_obj.sign(raw_time, ec.ECDSA(hashes.SHA256())).hex()
        with self.assertRaises(ConsensusError) as cm:
            self.core_c.verify_block_integrity(bad_time_block, time_hash_hex)
        self.assertIn('TIMESTAMP_DECREASING', str(cm.exception))

    def test_partition_reorg_convergence(self):
        """Test network partition and cumulative work reorganization.
        - Common ancestor is height 5.
        - Node B mines 1 block (height 6, weight = tip_5 + 1000).
        - Node C mines 2 blocks (height 6, 7, weight = tip_5 + 2000).
        - After partition heals, fork choice rule selects Node C's heavier chain.
        """
        priv_b = self.env.nodes['Node_B']['priv_pem']
        priv_c = self.env.nodes['Node_C']['priv_pem']
        tip_common = self.core_b.get_tip()

        # Branch B: 1 block
        res_b = self.core_b.mine_candidate_block(priv_b, tip_common['hash'], tip_common['timestamp'] + 60, [])
        with self.core_b.connection_scope() as db:
            b = res_b['block']
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (b['height'], res_b['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res_b['total_weight']))
            db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res_b['hash'], json.dumps(b['work'])))

        # Branch C: 2 blocks
        res_c1 = self.core_c.mine_candidate_block(priv_c, tip_common['hash'], tip_common['timestamp'] + 60, [])
        with self.core_c.connection_scope() as db:
            b = res_c1['block']
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (b['height'], res_c1['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res_c1['total_weight']))
            db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res_c1['hash'], json.dumps(b['work'])))

        res_c2 = self.core_c.mine_candidate_block(priv_c, res_c1['hash'], res_c1['block']['timestamp'] + 60, [])
        with self.core_c.connection_scope() as db:
            b = res_c2['block']
            db.execute('''
                INSERT INTO blocks (height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (b['height'], res_c2['hash'], b['previous_hash'], b['timestamp'], b['validator'], b['signature'], json.dumps(b['transactions']), res_c2['total_weight']))
            db.execute('INSERT INTO block_work (hash, proof) VALUES (?, ?)', (res_c2['hash'], json.dumps(b['work'])))

        # Check fork choice decisions
        tip_b_branch = self.core_b.get_tip()
        tip_c_branch = self.core_c.get_tip()

        self.assertGreater(tip_c_branch['total_weight'], tip_b_branch['total_weight'])
        # Node B should reorganize to Node C's chain
        self.assertTrue(self.core_b.should_reorganize(tip_c_branch, tip_b_branch))
        # Node C should NOT reorganize to Node B's chain
        self.assertFalse(self.core_c.should_reorganize(tip_b_branch, tip_c_branch))


if __name__ == '__main__':
    unittest.main()
