import json
from pathlib import Path
import tempfile
import unittest
import hashlib
import os
from unittest.mock import patch
from consensus_hold import start_permitted
from test_core import Fixture


class ConsensusHoldTests(unittest.TestCase):
    def test_sidechain_hold_in_production_is_network_scoped(self):
        with tempfile.TemporaryDirectory(prefix='ziokt-production-') as directory:
            path=Path(directory)/'consensus-safety-hold.json'
            path.write_text(json.dumps({'schema':'ziokt.consensus-safety-hold.v1','active':False}));path.chmod(0o600)
            with patch.dict(os.environ,{'CORIUM_NETWORK_ID_OVERRIDE':'ziokt-dna-side-20261024'}):
                self.assertTrue(start_permitted(path))
            with patch.dict(os.environ,{'CORIUM_NETWORK_ID_OVERRIDE':'ziokt-main'}):
                self.assertFalse(start_permitted(path))

    def test_boot_guard_requires_absent_or_explicitly_cleared_private_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hold.json'
            self.assertTrue(start_permitted(path))
            for value,expected in (({'schema':'ziokt.consensus-safety-hold.v1','active':True},False),
                                   ({'schema':'ziokt.consensus-safety-hold.v1','active':False},True),
                                   ({'active':False},False),([],False)):
                path.write_text(json.dumps(value));path.chmod(0o600)
                self.assertEqual(start_permitted(path),expected)
            path.chmod(0o644);self.assertFalse(start_permitted(path))
            link=Path(directory)/'alias';link.symlink_to(path)
            self.assertFalse(start_permitted(link))


class NativeMutationHoldTests(Fixture):
    def test_all_canonical_mutation_entries_reject_before_writing(self):
        path=self.root/'hold.json'
        path.write_text(json.dumps({'schema':'ziokt.consensus-safety-hold.v1','active':True}));path.chmod(0o600)
        self.env['CORIUM_CONSENSUS_HOLD_FILE']=str(path)
        before=hashlib.sha256(self.chain.read_bytes()).hexdigest()
        for command in ('blockchain_mine_block',
                        '_blockchain_reorganize_to '+'a'*64+' 127.0.0.1 9999',
                        '_internal_sync_fetch_new_blocks_to_stage "$CORIUM_ROOT/stage.db" 0',
                        '_internal_import_phoenix_state "$CORIUM_ROOT/missing.json"',
                        '_internal_rebuild_derived_state'):
            with self.subTest(entry=command.split()[0]):
                result=self.run_core(command,ok=False)
                self.assertIn('CONSENSUS_SAFETY_HOLD',result.stderr)
                self.assertEqual(hashlib.sha256(self.chain.read_bytes()).hexdigest(),before)


class MainnetRecoveryHoldTests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{'CORIUM_NETWORK_ID_OVERRIDE':'ziokt-main'})
        environment.start();self.addCleanup(environment.stop)
        os.environ.pop('CORIUM_ROOT',None)
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        self.priv = ec.generate_private_key(ec.SECP256K1())
        self.pub_pem = self.priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode().strip()
        self.val_id = hashlib.sha256(self.pub_pem.encode()).hexdigest()

    def _create_chain_db(self, path, tip=64, include_legacy=False, corrupt_h51=False):
        import sqlite3
        con = sqlite3.connect(path)
        cur = con.cursor()
        cur.execute('''CREATE TABLE blocks (
            height INTEGER PRIMARY KEY,
            hash TEXT UNIQUE NOT NULL,
            previous_hash TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            validator TEXT NOT NULL,
            transactions TEXT NOT NULL,
            total_weight INTEGER NOT NULL
        )''')
        cur.execute('INSERT INTO blocks VALUES (0, "h0", "0", 0, "g", "[]", 0)')
        prev = 'h0'
        for h in range(1, tip + 1):
            if h == 51 and corrupt_h51:
                hsh = "corrupt_h51"
            else:
                hsh = f"h{h}"
            cur.execute('INSERT INTO blocks VALUES (?, ?, ?, ?, "v", "[]", ?)', (h, hsh, prev, h, h*1000))
            prev = hsh
        if include_legacy:
            cur.execute('INSERT INTO blocks VALUES (784, "legacy784", "legacy783", 784, "v", "[]", 784000)')
        con.commit()
        con.close()

    def _sign_auth(self, auth):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        unsigned = {k: v for k, v in auth.items() if k != 'signature'}
        payload = json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode('utf-8')
        sig = self.priv.sign(b'Corium/RecoveryAuthorization/v1\0' + payload, ec.ECDSA(hashes.SHA256())).hex()
        auth['signature'] = sig
        return auth

    def test_mainnet_hold_security_matrix(self):
        with tempfile.TemporaryDirectory() as d:
            hold = Path(d) / 'consensus-safety-hold.json'
            db = Path(d) / 'chain.db'
            self._create_chain_db(db, tip=64)

            # 1. Missing file in mainnet mode -> fail-closed
            self.assertFalse(start_permitted(hold))

            # 2. Active hold -> blocked
            hold.write_text(json.dumps({'schema': 'ziokt.consensus-safety-hold.v1', 'active': True}))
            hold.chmod(0o600)
            self.assertFalse(start_permitted(hold))

            # 3. Active cleared (false) but no authorization -> blocked
            hold.write_text(json.dumps({'schema': 'ziokt.consensus-safety-hold.v1', 'active': False}))
            hold.chmod(0o600)
            self.assertFalse(start_permitted(hold))

            # Base valid authorization
            base_auth = {
                'schema': 'ziokt.recovery-authorization.v1',
                'network_id': 'ziokt-main',
                'chain_id': 'b' * 64,
                'genesis_hash': 'h0',
                'anchor_h50_hash': 'h50',
                'recovery_h51_hash': 'h51',
                'approved_checkpoint_height': 64,
                'approved_checkpoint_hash': 'h64',
                'canonical_database_path': str(db),
                'forbidden_legacy_hashes': ['legacy784'],
                'validator': self.val_id,
                'validator_pubkey': self.pub_pem,
                'authorized_at': 1792842000
            }

            # 4. Bad signature -> blocked
            bad_sig_auth = dict(base_auth)
            bad_sig_auth['signature'] = '00' * 64
            hold.write_text(json.dumps({'schema': 'ziokt.consensus-safety-hold.v1', 'active': False, 'authorized_recovery': bad_sig_auth}))
            hold.chmod(0o600)
            self.assertFalse(start_permitted(hold))

            # 5. Database containing forbidden legacy hash -> blocked
            legacy_db = Path(d) / 'legacy.db'
            self._create_chain_db(legacy_db, tip=64, include_legacy=True)
            leg_auth = dict(base_auth)
            leg_auth['canonical_database_path'] = str(legacy_db)
            self._sign_auth(leg_auth)
            hold.write_text(json.dumps({'schema': 'ziokt.consensus-safety-hold.v1', 'active': False, 'authorized_recovery': leg_auth}))
            hold.chmod(0o600)
            self.assertFalse(start_permitted(hold))

            # 6. Database with corrupted H51 -> blocked
            corrupt_db = Path(d) / 'corrupt.db'
            self._create_chain_db(corrupt_db, tip=64, corrupt_h51=True)
            corrupt_auth = dict(base_auth)
            corrupt_auth['canonical_database_path'] = str(corrupt_db)
            self._sign_auth(corrupt_auth)
            hold.write_text(json.dumps({'schema': 'ziokt.consensus-safety-hold.v1', 'active': False, 'authorized_recovery': corrupt_auth}))
            hold.chmod(0o600)
            self.assertFalse(start_permitted(hold))

            # 7. Valid recovery chain and signed authorization -> permitted
            valid_auth = dict(base_auth)
            self._sign_auth(valid_auth)
            hold.write_text(json.dumps({'schema': 'ziokt.consensus-safety-hold.v1', 'active': False, 'authorized_recovery': valid_auth}))
            hold.chmod(0o600)
            self.assertTrue(start_permitted(hold))

            # A signed declaration cannot bless a branch with a missing height,
            # even if the remaining predecessor hashes were edited to join up.
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(db)) as chain,chain:
                chain.execute('DELETE FROM blocks WHERE height=55')
                chain.execute("UPDATE blocks SET previous_hash='h54' WHERE height=56")
            self.assertFalse(start_permitted(hold))

