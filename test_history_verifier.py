"""History coverage is explicit; policy weight checks survive Python -O."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from verify_mainnet_history import GENESIS_HASH, verify_history


class HistoryVerifierTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'history.db')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE blocks (height INTEGER PRIMARY KEY, hash TEXT, previous_hash TEXT, '
                       'timestamp INTEGER, validator TEXT, signature TEXT, transactions TEXT, total_weight INTEGER)')
            db.execute('CREATE TABLE block_work (hash TEXT, proof TEXT)')
            parent = '0'
            for height in range(65):
                identity = GENESIS_HASH if height == 0 else f'{height:064x}'
                db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)',
                           (height, identity, parent, height, 'fixture', '', '[]', height if height < 64 else 70))
                parent = identity
            db.execute('INSERT INTO block_work VALUES (?,?)', (parent, '{}'))

    def test_uses_verified_policy_weight_and_reports_partial_coverage(self):
        with patch('verify_mainnet_history.work.verify', return_value={'work_verified': True, 'total_weight': 70}), redirect_stdout(StringIO()):
            report = verify_history(self.path)
        self.assertEqual(report['status'], 'PARTIALLY_VERIFIED')
        self.assertFalse(report['full_history_verified'])
        self.assertFalse(report['coverage']['legacy_pos_signatures'])
        self.assertFalse(report['coverage']['application_state_commitments'])

    def test_incorrect_weight_and_parent_are_rejected(self):
        with patch('verify_mainnet_history.work.verify', return_value={'work_verified': True, 'total_weight': 71}), redirect_stdout(StringIO()):
            with self.assertRaisesRegex(ValueError, 'total_weight mismatch'):
                verify_history(self.path)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE blocks SET previous_hash='forged' WHERE height=1")
        with redirect_stdout(StringIO()), self.assertRaisesRegex(ValueError, 'broken parent link'):
            verify_history(self.path)

    def test_full_verification_request_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Full independent history verification is unavailable'):
            verify_history(self.path, require_full=True)


if __name__ == '__main__':
    unittest.main()
