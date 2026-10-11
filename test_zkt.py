"""Real native ZKT testchain: signed genesis, native mining, replay and Phoenix.

All keys and issuance are temporary test data; no external peers or mainnet.
"""
from contextlib import closing
import hashlib
import json
import shlex
import sqlite3

from test_core import Fixture
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class ZKTChainTests(Fixture):
    def setUp(self):
        super().setUp()
        self.bob_key = ec.generate_private_key(ec.SECP256K1())
        self.bob_pem = self.bob_key.public_key().public_bytes(serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip("\n")
        self.bob = hashlib.sha256(self.bob_pem.encode()).hexdigest()
        self.treasury = "c" * 64
        self.policy = {"schema": "ziokt.zkt-genesis.v1", "symbol": "ZKT", "network_id": "zkt-test-only",
                       "authority": self.identity, "decimals": 3, "total_units": 1_000_000,
                       "allocations": [{"address": self.identity, "units": 900_000},
                                       {"address": self.bob, "units": 100_000}],
                       "fee_units": 7, "fee_recipient": self.treasury}
        self.asset = "sha256:" + hashlib.sha256(canonical(self.policy)).hexdigest()
        self.policy["signature"] = self.key.sign(b"Ziokt/ZKT/genesis/v1\n" + canonical(self.policy), ec.ECDSA(hashes.SHA256())).hex()
        genesis = json.loads((self.etc / "genesis.json").read_text())
        genesis["ziokt_zkt"] = self.policy
        (self.etc / "genesis.json").write_text(json.dumps(genesis))
        self.run_core('db_execute_safe "$BLOCKCHAIN_DB" "DELETE FROM blocks; DELETE FROM validators; DELETE FROM chain_state;"; blockchain_create_genesis_block; _update_chain_state_cache')

    def balances(self):
        with closing(sqlite3.connect(self.chain)) as db, db:
            return {r[0]: (r[1], r[2]) for r in db.execute("SELECT address,balance,nonce FROM zkt_accounts")}

    def payload(self, **changes):
        return {"schema": "ziokt.zkt-transfer.v1", "asset_id": self.asset, "network_id": "zkt-test-only",
                "from": self.identity, "to": self.bob, "units": 1000, "fee_units": 7, "nonce": 1, **changes}

    def transfer(self, **changes):
        payload = json.dumps(self.payload(**changes), ensure_ascii=False, separators=(",", ":"))
        result = self.run_core("blockchain_create_transaction ziokt_zkt_transfer_v1 " + shlex.quote(payload))
        return result.stdout.strip().splitlines()[-1]

    def test_fixed_supply_signed_genesis_and_no_second_issuance(self):
        self.assertEqual(self.balances(), {self.identity: (900000, 0), self.bob: (100000, 0)})
        self.run_core('_ziokt_zkt_engine genesis "$BLOCKCHAIN_DB" "$GENESIS_CONFIG_FILE"', ok=False)
        self.assertEqual(sum(v[0] for v in self.balances().values()), 1_000_000)
        legacy = hashlib.sha256(b'{"height":0,"previous_hash":"0","timestamp":0,"transactions":[]}').hexdigest()
        with closing(sqlite3.connect(self.chain)) as db, db:
            self.assertNotEqual(db.execute("SELECT hash FROM blocks WHERE height=0").fetchone()[0], legacy)

    def test_real_native_mining_transfer_fee_and_sequential_nonce(self):
        self.transfer(); self.run_core("blockchain_mine_block")
        self.assertEqual(self.balances()[self.identity], (898993, 1))
        self.assertEqual(self.balances()[self.bob], (101000, 0))
        self.assertEqual(self.balances()[self.treasury], (7, 0))
        self.transfer(units=2000, nonce=2); self.run_core("blockchain_mine_block")
        self.assertEqual(self.balances()[self.identity], (896986, 2))
        self.assertEqual(sum(v[0] for v in self.balances().values()), 1_000_000)
        with closing(sqlite3.connect(self.chain)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM zkt_transfers").fetchone()[0], 2)

    def test_same_block_double_spend_is_rejected_atomically(self):
        self.transfer(units=500_000)
        self.transfer(units=499_999)
        before = self.balances()
        self.run_core("blockchain_mine_block", ok=False)
        self.assertEqual(self.balances(), before)
        with closing(sqlite3.connect(self.chain)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0], 1)

    def test_replay_wrong_network_asset_signer_fee_and_bad_amounts(self):
        for change in ({"nonce": 0}, {"units": True}, {"units": 0}, {"units": -1},
                       {"units": 900000}, {"network_id": "different"}, {"asset_id": "sha256:" + "0" * 64},
                       {"from": self.bob}, {"fee_units": 0}, {"extra": True}):
            with self.subTest(change=change):
                tx = self.transfer(**change)
                before = self.balances()
                self.run_core("blockchain_mine_block", ok=False)
                self.assertEqual(self.balances(), before)
                with closing(sqlite3.connect(self.chain)) as db, db:
                    db.execute("DELETE FROM transactions WHERE hash=?", (tx,))
        self.transfer(); self.run_core("blockchain_mine_block")
        self.transfer(units=500, nonce=1)
        before = self.balances(); self.run_core("blockchain_mine_block", ok=False)
        self.assertEqual(self.balances(), before)

    def test_bad_native_signature_cannot_commit(self):
        tx = self.transfer()
        with closing(sqlite3.connect(self.chain)) as db, db:
            db.execute("UPDATE transactions SET signature='00' WHERE hash=?", (tx,))
        before = self.balances(); self.run_core("blockchain_mine_block", ok=False)
        self.assertEqual(self.balances(), before)

    def test_canonical_replay_rebuilds_corrupted_balances(self):
        self.transfer(); self.run_core("blockchain_mine_block")
        expected = self.balances()
        with closing(sqlite3.connect(self.chain)) as db, db:
            db.execute("UPDATE zkt_accounts SET balance=0")
        self.run_core("_internal_rebuild_derived_state")
        self.assertEqual(self.balances(), expected)

    def test_phoenix_preserves_asset_supply_and_nonce_then_can_continue(self):
        self.transfer(); self.run_core("blockchain_mine_block")
        snapshot = self.snapshot(height=1)
        expected = self.balances()
        with closing(sqlite3.connect(self.chain)) as db, db:
            db.execute("DELETE FROM blocks"); db.execute("DELETE FROM transactions")
            db.execute("DELETE FROM zkt_accounts"); db.execute("DELETE FROM zkt_meta"); db.execute("DELETE FROM zkt_transfers")
        self.import_snapshot(snapshot)
        self.assertEqual(self.balances(), expected)
        with closing(sqlite3.connect(self.chain)) as db, db:
            self.assertEqual(db.execute("SELECT value FROM zkt_meta WHERE key='asset_id'").fetchone()[0], self.asset)
        (self.etc / "genesis.json").write_text(json.dumps(snapshot))
        self.transfer(nonce=2, units=500); self.run_core("blockchain_mine_block")
        self.assertEqual(self.balances()[self.identity], (898486, 2))

    def test_phoenix_cannot_inflate_supply_even_with_valid_snapshot_signature(self):
        snapshot = self.snapshot()
        snapshot["state"]["chain_tables"]["zkt_accounts"][0]["balance"] += 1
        snapshot.pop("state_root"); snapshot.pop("snapshot_signature")
        root = hashlib.sha256(canonical(snapshot)).hexdigest()
        snapshot.update(state_root=root, snapshot_signature=self.sign(root))
        before = self.balances()
        self.import_snapshot(snapshot, ok=False)
        self.assertEqual(self.balances(), before)
