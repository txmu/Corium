"""Comprehensive unit tests for versioned GIMPS consensus, task state lifecycle, and settlement."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import gimps_consensus as GIMPS


class GimpsConsensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_chain.db"
        with sqlite3.connect(self.db_path) as db:
            db.execute("""
            CREATE TABLE blocks (
                height INTEGER PRIMARY KEY,
                hash TEXT NOT NULL,
                transactions TEXT
            )
            """)
            db.execute("""
            CREATE TABLE transactions (
                hash TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                public_key TEXT NOT NULL,
                signature TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                block_height INTEGER
            )
            """)
            db.execute("""
            CREATE TABLE compute_engines (
                engine_id TEXT PRIMARY KEY,
                pkg_id TEXT NOT NULL,
                description TEXT,
                compute_program_hash TEXT NOT NULL,
                verifier_script_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                reward_weight INTEGER NOT NULL DEFAULT 100
            )
            """)
            db.execute("""
            CREATE TABLE problem_sets (
                set_id TEXT PRIMARY KEY,
                engine_id TEXT NOT NULL,
                metadata TEXT NOT NULL,
                activation_height INTEGER
            )
            """)
            db.execute("""
            CREATE TABLE pending_proofs (
                problem_id TEXT PRIMARY KEY,
                proof_tx_hash TEXT NOT NULL,
                proposer_id TEXT NOT NULL,
                proposed_result TEXT NOT NULL,
                confirmation_deadline_height INTEGER NOT NULL
            )
            """)
            db.execute("""
            CREATE TABLE completed_compute_tasks (
                engine_id TEXT,
                problem_id TEXT,
                proof_tx_hash TEXT NOT NULL,
                PRIMARY KEY (engine_id, problem_id)
            )
            """)
            db.execute("""
            CREATE TABLE challenges (
                challenge_tx_hash TEXT PRIMARY KEY,
                target_proof_tx_hash TEXT NOT NULL,
                challenger_id TEXT NOT NULL,
                challenge_data TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
            """)
            db.execute("""
            CREATE TABLE contribution_scores (
                user_id TEXT PRIMARY KEY,
                score INTEGER NOT NULL DEFAULT 0,
                last_update_height INTEGER NOT NULL
            )
            """)
            db.execute(
                "INSERT INTO compute_engines VALUES(?,?,?,?,?,?,?)",
                ('gimps-ci', 'corium/built-in-gimps', 'GIMPS LLT Engine', 'hash_prog', 'hash_ver', 1, 150)
            )
            db.execute(
                "INSERT INTO problem_sets VALUES(?,?,?,?)",
                ('ps-1', 'gimps-ci', json.dumps({'start_exponent': 5, 'end_exponent': 7}), 0)
            )
            db.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_portable_large_residue_and_native_independent_challenge(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute('CREATE TABLE chain_state (key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO blocks VALUES (1,?,?)',('a'*64,'[]'))
            db.execute('INSERT INTO chain_state VALUES (?,?)',('chain_info','a'*64+'|1'))
            before=db.total_changes
            job=GIMPS.native_challenge(db,'test-net','user-a')
            self.assertEqual(job['engine_id'],'gimps-ci');self.assertEqual(job['exponent'],5)
            self.assertEqual(db.total_changes,before,'challenge must remain read-only')
            db.execute("UPDATE problem_sets SET metadata=?",(json.dumps({'start_exponent':2,'end_exponent':127}),))
            _,residue=GIMPS.lucas_lehmer_verify(67,0)
            self.assertGreater(residue,2**53)
            proof={'schema':GIMPS.PORTABLE_SCHEMA,'exponent':67,'method':'lucas-lehmer','residue':str(residue),'is_prime':False,'iterations':65}
            payload={'engine_id':'gimps-ci','problem_id':'67','proof_data':proof}
            self.assertEqual(GIMPS.validate_gimps_proof(db,'test-net',payload,'user-a',1)['status'],'valid')
            proof['residue']='0'+proof['residue']
            with self.assertRaises(ValueError):GIMPS.validate_gimps_proof(db,'test-net',payload,'user-a',1)
            db.execute('UPDATE compute_engines SET is_active=0')
            self.assertFalse(GIMPS.native_challenge(db,'test-net','user-a')['available'])

    def test_lucas_lehmer_verify(self):
        # M_3 = 2^3 - 1 = 7 (prime, s=0)
        valid, s = GIMPS.lucas_lehmer_verify(3, 0)
        self.assertTrue(valid)
        self.assertEqual(s, 0)

        # M_5 = 31 (prime, s=0)
        valid, s = GIMPS.lucas_lehmer_verify(5, 0)
        self.assertTrue(valid)
        self.assertEqual(s, 0)

        # M_7 = 127 (prime, s=0)
        valid, s = GIMPS.lucas_lehmer_verify(7, 0)
        self.assertTrue(valid)
        self.assertEqual(s, 0)

        # M_11 = 2047 = 23 * 89 (composite, s != 0)
        valid, s = GIMPS.lucas_lehmer_verify(11, 0)
        self.assertFalse(valid)
        self.assertNotEqual(s, 0)

    def test_task_state_machine_and_retry_not_permanently_skipped(self):
        with sqlite3.connect(self.db_path) as db:
            meta = {'start_exponent': 5, 'end_exponent': 7}
            # First task: assigns 5
            task1 = GIMPS.generate_next_gimps_task(db, 'gimps-ci', 'ps-1', meta, current_time=1000)
            self.assertEqual(task1, '5|5')

            # Only prime exponents are useful LL tasks; composite 6 is skipped
            task2 = GIMPS.generate_next_gimps_task(db, 'gimps-ci', 'ps-1', meta, current_time=1001)
            self.assertEqual(task2, '7|7')

            # Next task is 7
            task3 = GIMPS.generate_next_gimps_task(db, 'gimps-ci', 'ps-1', meta, current_time=1002)
            self.assertIsNone(task3)

            # Now all 5, 6, 7 are assigned (in-flight) -> none available
            task4 = GIMPS.generate_next_gimps_task(db, 'gimps-ci', 'ps-1', meta, current_time=1003)
            self.assertIsNone(task4)

            # Suppose 6 submitted a proof and was settled into completed_compute_tasks
            db.execute("INSERT INTO completed_compute_tasks VALUES (?, ?, ?)", ('gimps-ci', '6', 'tx-6'))
            # Suppose 7 submitted a proof and is in pending_proofs
            db.execute("INSERT INTO pending_proofs VALUES (?, ?, ?, ?, ?)", ('7', 'tx-7', 'user-1', '{}', 20))
            # But task 5 was challenged and failed!
            db.execute("""
            INSERT INTO transactions VALUES ('tx-5', 'submit_math_proof', ?, 'pubkey', 'sig', 1000, 5)
            """, (json.dumps({'engine_id': 'gimps-ci', 'problem_id': '5', 'proof_data': {}}),))
            db.execute("INSERT INTO challenges VALUES ('c-5', 'tx-5', 'challenger', 'data', 'confirmed')")
            db.commit()

            # Now generate task at current_time=1700 (lease for 5 expired, and 5 failed)
            # Exponent 5 MUST BE RETRIED, NOT PERMANENTLY SKIPPED!
            retry_task = GIMPS.generate_next_gimps_task(db, 'gimps-ci', 'ps-1', meta, current_time=1700)
            self.assertEqual(retry_task, '5|5')

    def test_validate_versioned_and_legacy_proofs(self):
        with sqlite3.connect(self.db_path) as db:
            # Valid versioned proof
            valid_payload = {
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {
                    'schema': 'corium.gimps-proof.v1',
                    'exponent': 5,
                    'method': 'lucas-lehmer',
                    'residue': 0,
                    'is_prime': True,
                    'iterations': 3
                }
            }
            res = GIMPS.validate_gimps_proof(db, 'test-net', valid_payload, 'user-a', 10)
            self.assertEqual(res['status'], 'valid')
            self.assertEqual(res['exponent'], 5)
            self.assertEqual(res['reward'], 15000)  # 100 * 150

            # Fraudulent versioned proof (claiming prime with wrong residue)
            fraud_payload = {
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {
                    'schema': 'corium.gimps-proof.v1',
                    'exponent': 5,
                    'method': 'lucas-lehmer',
                    'residue': 42,
                    'is_prime': True,
                    'iterations': 3
                }
            }
            with self.assertRaises(ValueError):
                GIMPS.validate_gimps_proof(db, 'test-net', fraud_payload, 'user-a', 10)

            # Valid legacy proof
            legacy_payload = {
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {'residue': 0}
            }
            res2 = GIMPS.validate_gimps_proof(db, 'test-net', legacy_payload, 'user-a', 10)
            self.assertEqual(res2['status'], 'valid')

    def test_duplicate_submission_prevented(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT INTO completed_compute_tasks VALUES (?, ?, ?)", ('gimps-ci', '5', 'tx-5-done'))
            db.commit()

            payload = {
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {'residue': 0}
            }
            with self.assertRaises(ValueError):
                GIMPS.validate_gimps_proof(db, 'test-net', payload, 'user-a', 10)

    def test_settle_proof_and_contribution_scores(self):
        with sqlite3.connect(self.db_path) as db:
            pubkey = "secp256k1_pubkey_user_abc"
            sender = hashlib.sha256(pubkey.encode()).hexdigest()
            tx_data = json.dumps({
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {
                    'schema': 'corium.gimps-proof.v1',
                    'exponent': 5,
                    'method': 'lucas-lehmer',
                    'residue': 0,
                    'is_prime': True,
                    'iterations': 3
                }
            })
            tx_hash = "tx_gimps_5"
            db.execute("""
            INSERT INTO transactions VALUES (?, 'submit_math_proof', ?, ?, 'sig', 1000, 10)
            """, (tx_hash, tx_data, pubkey))
            # Put in pending_proofs with deadline at height 20
            db.execute("""
            INSERT INTO pending_proofs VALUES ('5', ?, ?, '{}', 20)
            """, (tx_hash, sender))
            db.commit()

            # At height 19, cannot settle yet
            with self.assertRaises(ValueError):
                GIMPS.settle(db, 'test-net', tx_hash, 19)

            # At height 20, settle succeeds!
            res = GIMPS.settle(db, 'test-net', tx_hash, 20)
            self.assertEqual(res['settled_height'], 20)
            self.assertEqual(res['contribution_score'], 15000)

            # Verified recorded in completed_compute_tasks
            done = db.execute("SELECT proof_tx_hash FROM completed_compute_tasks WHERE engine_id='gimps-ci' AND problem_id='5'").fetchone()
            self.assertIsNotNone(done)
            self.assertEqual(done[0], tx_hash)

            # Pending proof deleted
            pending = db.execute("SELECT 1 FROM pending_proofs WHERE proof_tx_hash=?", (tx_hash,)).fetchone()
            self.assertIsNone(pending)

            # Contribution score credited
            score = db.execute("SELECT score FROM contribution_scores WHERE user_id=?", (sender,)).fetchone()[0]
            self.assertEqual(score, 15000)

    def test_challenge_gimps_proof(self):
        with sqlite3.connect(self.db_path) as db:
            pubkey = "secp256k1_pubkey_user_valid"
            valid_data = json.dumps({
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {
                    'schema': 'corium.gimps-proof.v1',
                    'exponent': 5,
                    'method': 'lucas-lehmer',
                    'residue': 0,
                    'is_prime': True,
                    'iterations': 3
                }
            })
            db.execute("INSERT INTO transactions VALUES ('tx_valid', 'submit_math_proof', ?, ?, 'sig', 1000, 10)", (valid_data, pubkey))
            # When valid proof is challenged, validate_challenge returns 1 (proof is valid, challenge fails)
            self.assertEqual(GIMPS.validate_challenge(db, 'test-net', 'tx_valid'), 1)

            # Insert an invalid proof (fraudulent residue for p=5)
            fraud_data = json.dumps({
                'engine_id': 'gimps-ci',
                'problem_id': '5',
                'proof_data': {
                    'schema': 'corium.gimps-proof.v1',
                    'exponent': 5,
                    'method': 'lucas-lehmer',
                    'residue': 99,
                    'is_prime': True,
                    'iterations': 3
                }
            })
            db.execute("INSERT INTO transactions VALUES ('tx_fraud', 'submit_math_proof', ?, ?, 'sig', 1000, 10)", (fraud_data, pubkey))
            # When fraudulent proof is challenged, validate_challenge returns 0 (proof invalid, challenge succeeds)
            self.assertEqual(GIMPS.validate_challenge(db, 'test-net', 'tx_fraud'), 0)


if __name__ == '__main__':
    unittest.main()
