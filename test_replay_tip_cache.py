"""Native replay must expose the verified tip to subsequent native mining."""
import sqlite3
from test_core import Fixture

class ReplayTipCacheTests(Fixture):
 def test_replayed_tip_matches_verified_block(self):
  self.run_core('blockchain_create_transaction set_nickname \'{"nickname":"replay-tip-regression"}\'; blockchain_mine_block')
  expected=sqlite3.connect(self.chain).execute('SELECT hash FROM blocks WHERE height=1').fetchone()[0]
  replay=self.root/'replay-tip';replay.mkdir()
  self.run_core('_internal_replay_chain_state 1 "'+str(replay)+'"')
  with sqlite3.connect(replay/'chain.db') as db:
   self.assertEqual(db.execute("SELECT value FROM chain_state WHERE key='chain_info'").fetchone()[0],expected+'|1')
 def test_stale_cache_cannot_choose_a_noncanonical_mining_parent(self):
  self.run_core('blockchain_create_transaction set_nickname \'{"nickname":"canonical-tip"}\'; blockchain_mine_block')
  with sqlite3.connect(self.chain) as db:
   expected=db.execute('SELECT hash FROM blocks WHERE height=1').fetchone()[0]
   db.execute("INSERT OR REPLACE INTO chain_state VALUES('chain_info',?)",('f'*64+'|999',))
  self.assertEqual(self.run_core('blockchain_get_latest_hash').stdout.strip(),expected)
  self.run_core('blockchain_create_transaction set_nickname \'{"nickname":"canonical-tip-next"}\'; blockchain_mine_block')
  with sqlite3.connect(self.chain) as db:
   self.assertEqual(db.execute('SELECT previous_hash FROM blocks WHERE height=2').fetchone()[0],expected)
