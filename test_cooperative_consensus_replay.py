import json
import sqlite3
import unittest
from unittest.mock import patch

import cooperative_protocol as coop
import work_consensus as consensus
from cryptography.hazmat.primitives.asymmetric import ec


class CooperativeConsensusReplayTests(unittest.TestCase):
    def test_state_is_rebuilt_from_canonical_prefix_and_ignores_stale_cache(self):
        keys=[ec.generate_private_key(ec.SECP256K1()) for _ in range(3)]
        chain='a'*64
        state=coop.empty(chain)
        command={'schema':'corium.cooperative-command.v1','chain':chain,'cooperative':'workers',
                 'sequence':1,'previous_state':coop.state_root(state),'action':'create',
                 'arguments':{'members':[coop.public_key(key) for key in keys]}}
        envelope={'command':command,'endorsements':[coop.endorse(command,key) for key in keys]}
        expected=coop.apply(state,command,envelope['endorsements'])
        db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        db.executescript('CREATE TABLE blocks(height INTEGER,transactions TEXT);'
                         'CREATE TABLE transactions(hash TEXT,type TEXT,data TEXT,block_height INTEGER);'
                         'CREATE TABLE cooperative_registry(id INTEGER,state TEXT);')
        db.execute('INSERT INTO blocks VALUES(2,?)',(json.dumps(['tx1']),))
        db.execute('INSERT INTO transactions VALUES(?,?,?,?)',
                   ('tx1','cooperative_command',json.dumps(envelope),2))
        db.execute('INSERT INTO cooperative_registry VALUES(1,?)',
                   (json.dumps(coop.empty('b'*64)),))
        declaration={'checkpoint':{'height':1}}
        with patch.object(consensus.Recovery,'declaration',return_value=declaration), \
             patch.object(consensus.Recovery,'identity',return_value=chain):
            rebuilt=consensus.cooperative_state_at(db,'test-network',3)
            self.assertEqual(rebuilt,expected)
            self.assertEqual(consensus.Cooperative.state_root(rebuilt),coop.state_root(expected))
            db.execute('DELETE FROM blocks')
            self.assertEqual(consensus.cooperative_state_at(db,'test-network',3),state)

    def test_previously_approved_recovery_source_pin_is_preserved(self):
        db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        db.executescript('CREATE TABLE blocks(height INTEGER,hash TEXT,transactions TEXT);'
                         'CREATE TABLE compute_engines(compute_program_hash TEXT,verifier_script_hash TEXT,'
                         'pkg_id TEXT,is_active INTEGER,engine_id TEXT);'
                         'CREATE TABLE transactions(hash TEXT,type TEXT,data TEXT,block_height INTEGER);')
        db.execute('INSERT INTO blocks VALUES(0,?,?)',('f'*64,'[]'))
        old=next(iter(consensus.LEGACY_SOURCE_DIGESTS))
        declaration={'verifier_source_sha256':old,'checkpoint':{'height':1}}
        with patch.object(consensus.Recovery,'declaration',return_value=declaration), \
             patch.object(consensus.Recovery,'active',return_value=None) as recovery_active, \
             patch.object(consensus,'source_digest',return_value='e'*64):
            self.assertIsNone(consensus.active(db,'ziokt-main-recovery-20261024',52))
            self.assertEqual(recovery_active.call_args.args[3],old)


if __name__=='__main__':
    unittest.main()
