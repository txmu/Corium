"""Full native replay precedes adoption; a checksum alone never admits a ledger."""
import hashlib,os,pathlib,sqlite3,subprocess
from test_core import Fixture
TOOL=pathlib.Path(__file__).resolve().parents[1]/'Ziokt/tools/sync_native_snapshot.py'

class VerifiedSnapshotTests(Fixture):
    def test_native_adoption_and_bad_signature_rollback_keep_identity(self):
        key=(self.etc/'identity.key').read_bytes();snapshot=self.root/'snapshot.db'
        for height in (1,2):self.add_empty_block(height)
        with sqlite3.connect(self.chain) as source,sqlite3.connect(snapshot) as target:source.backup(target)
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM blocks WHERE height>0')
        def run(ok):
            digest=hashlib.sha256(snapshot.read_bytes()).hexdigest()
            result=subprocess.run(['python3',str(TOOL),'--source',str(pathlib.Path(__file__).with_name('corix_v108.sh')),'--root',str(self.root),'--network','default','--snapshot',str(snapshot),'--sha256',digest,'--apply'],env=self.env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode==0,ok,result.stdout+result.stderr)
        run(True)
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT MAX(height) FROM blocks').fetchone()[0],2)
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute("SELECT value FROM chain_state WHERE key='last_processed_height'").fetchone()[0],'2')
        before=self.semantic()
        self.run_core('_update_chain_state_cache')
        self.assertEqual(self.semantic(),before)
        with sqlite3.connect(snapshot) as db:db.execute("UPDATE blocks SET signature='00' WHERE height=2")
        run(False);self.assertEqual(self.semantic(),before)
        self.assertEqual((self.etc/'identity.key').read_bytes(),key)

    def test_event_window_falls_back_for_pending_proofs_and_group_votes(self):
        self.run_core('_internal_empty_event_window 1 2')
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO pending_proofs VALUES(?,?,?,?,?)',('p','a'*64,self.identity,'{}',900))
        self.run_core('_internal_empty_event_window 1 2',False)
        with sqlite3.connect(self.chain) as db:
            db.execute('DELETE FROM pending_proofs')
            db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?)',('a'*64,'group_propose_owner','{}','00',self.pem,1,1))
        self.run_core('_internal_empty_event_window 500 501',False)
        self.run_core('_internal_empty_event_window 502 503')
