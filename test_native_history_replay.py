"""Exercise actual legacy signatures/transactions through genesis replay."""
import sqlite3
from test_core import Fixture, SOURCE
from verify_mainnet_history import replay_native_history


class NativeHistoryReplayTests(Fixture):
    def test_legacy_replay_reconstructs_and_rejects_forged_signature(self):
        self.run_core('blockchain_create_transaction set_nickname \'{"nickname":"replay-check"}\' >/dev/null; blockchain_mine_block >/dev/null')
        first = replay_native_history(str(self.root), 1, 'default', str(SOURCE))
        second = replay_native_history(str(self.root), 1, 'default', str(SOURCE))
        self.assertEqual(first['reconstructed_state_digest'], second['reconstructed_state_digest'])
        self.assertFalse(first['on_chain_state_commitment_verified'])
        with sqlite3.connect(self.chain) as db:
            signature = db.execute('SELECT signature FROM blocks WHERE height=1').fetchone()[0]
            db.execute("UPDATE blocks SET signature='00' WHERE height=1")
        with self.assertRaisesRegex(ValueError, 'Native history replay rejected'):
            replay_native_history(str(self.root), 1, 'default', str(SOURCE))
        with sqlite3.connect(self.chain) as db:
            db.execute('UPDATE blocks SET signature=? WHERE height=1', (signature,))
            db.execute("UPDATE transactions SET signature='00' WHERE block_height=1")
        with self.assertRaisesRegex(ValueError, 'Native history replay rejected'):
            replay_native_history(str(self.root), 1, 'default', str(SOURCE))
