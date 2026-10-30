"""Real native TLS fast-forward must enact the governed verifier before selection.

The policy registry setup is an isolated unit fixture, not mainnet voting proof.
"""
import json,sqlite3
from test_work_consensus import NativeWorkConsensusUnits
from test_reorg import ReorgTests
import work_consensus as work

class ActivationReorgTests(NativeWorkConsensusUnits,ReorgTests):
 def tip(self,path=None):
  return NativeWorkConsensusUnits.tip(self) if path is None else ReorgTests.tip(self,path)
 def test_activation_boundary_fast_forward(self):
  candidate=self.candidate();block=candidate['block']
  with sqlite3.connect(self.chain) as source,sqlite3.connect(self.remote) as remote:
   source.backup(remote)
   remote.row_factory=sqlite3.Row
   remote.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?)',(block['height'],candidate['hash'],block['previous_hash'],block['timestamp'],block['validator'],block['signature'],json.dumps(block['transactions'],separators=(',',':')),candidate['total_weight']))
   work.record(remote,self.network_id,block,candidate['hash'])
  with sqlite3.connect(self.chain) as db:
   proposal=db.execute('SELECT data FROM transactions WHERE hash=?',(self.engine,)).fetchone()[0]
   db.execute('UPDATE compute_engines SET is_active=0 WHERE engine_id=?',(self.engine,))
   db.execute('INSERT INTO scheduled_state_changes VALUES(?,?,?,?)',(self.engine,111,'propose_new_compute_engine',proposal))
  self.reorganize(candidate['hash'])
  self.assertEqual(self.tip()['height'],111)
  with sqlite3.connect(self.chain) as db:
   db.row_factory=sqlite3.Row
   self.assertTrue(work.verify(db,self.network_id,work.stored(db,candidate['hash']),candidate['hash'])['work_verified'])

def load_tests(loader,standard_tests,pattern):
 """Run the new boundary case; fixture-base cases run in their own modules."""
 import unittest
 return unittest.TestSuite([ActivationReorgTests('test_activation_boundary_fast_forward')])
