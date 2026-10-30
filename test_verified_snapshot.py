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
        before=self.semantic()
        with sqlite3.connect(snapshot) as db:db.execute("UPDATE blocks SET signature='00' WHERE height=2")
        run(False);self.assertEqual(self.semantic(),before)
        self.assertEqual((self.etc/'identity.key').read_bytes(),key)
