"""Run the real native signed transaction/miner/rebuild path, no replacement chain."""
import json
import shlex
import sqlite3
from test_core import Fixture


class PrivacyConsensusTests(Fixture):
    def test_signed_chainwide_request_vote_and_derived_state_rebuild(self):
        request={'network_id':'default','case_commitment':'d'*64,'legal_basis_commitment':'e'*64,
                 'recipient_key':'f'*64,'scope':['a'*64],'expires_height':100,'nonce':'8'*64}
        self.run_core('blockchain_create_transaction privacy_review_request '+shlex.quote(json.dumps(request))+' >/dev/null; blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            identifier=db.execute('SELECT request_id FROM privacy_requests').fetchone()[0]
            self.assertEqual(db.execute('SELECT voter FROM privacy_electorate').fetchall(),[(self.identity,)])
        vote={'network_id':'default','request_id':identifier,'decision':'approve'}
        self.run_core('blockchain_create_transaction privacy_review_vote '+shlex.quote(json.dumps(vote))+' >/dev/null; blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            before=db.execute('SELECT request_id,voter,decision FROM privacy_votes').fetchall()
            self.assertEqual(before,[(identifier,self.identity,'approve')])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM privacy_disclosures').fetchone()[0],0)
        self.run_core('_internal_rebuild_derived_state')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT request_id,voter,decision FROM privacy_votes').fetchall(),before)


if __name__=='__main__':
    import unittest
    unittest.main()
