"""Detect off-chain activation without changing the source database."""
import json
import hashlib
import sqlite3
from audit_history_provenance import audit
from test_core import Fixture


class ProvenanceTests(Fixture):
    def test_off_chain_governance_is_rejected_and_legacy_signature_checked(self):
        self.add_empty_block(1)
        proposal='a'*64
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)',
                       (proposal,'propose_new_compute_engine','{}','00',self.pem,1,1))
            db.execute('INSERT INTO compute_engines VALUES (?,?,?,?,?,1,1)',
                       (proposal,'consensus/work-weight:2','fixture','b'*64,'c'*64))
        before=hashlib.sha256(self.chain.read_bytes()).hexdigest()
        report=audit(self.chain,self.etc/'genesis.json')
        self.assertEqual(report['status'],'REJECTED')
        self.assertEqual(report['legacy_headers_and_signatures_checked'],1)
        self.assertEqual(report['errors'][0]['code'],'WORK_GOVERNANCE_NOT_COMMITTED')
        self.assertFalse(report['full_history_verified'])
        self.assertFalse(report['source_databases_modified'])
        self.assertEqual(hashlib.sha256(self.chain.read_bytes()).hexdigest(),before)
        with sqlite3.connect(self.chain) as db:
            db.execute("UPDATE blocks SET signature='00' WHERE height=1")
        report=audit(self.chain,self.etc/'genesis.json')
        self.assertIn('LEGACY_HEADER_OR_SIGNATURE_INVALID',[error['code'] for error in report['errors']])
