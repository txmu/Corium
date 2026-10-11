"""Signed custom schema activation, replay, Phoenix and transaction rollback."""
import base64
import hashlib
import io
import json
import shlex
import sqlite3
import tarfile
from test_core import Fixture
from test_pgp_fixture import OpenPGPFixture

class Templates(Fixture):
    core_timeout = 900
    def schedule(self, schema, label='ci', version=1, bad_signature=False):
        if not hasattr(self,'signer'): self.signer=OpenPGPFixture()
        signer = self.signer
        zone = self.etc/'trust_zones/apps'; zone.mkdir(parents=True,exist_ok=True)
        (zone/'keyring.gpg').write_bytes(signer.keyring())
        (self.etc/'world').write_text('')
        archive = self.root/(label+'.tar.gz')
        files = {'.corium/template.build':f'pkgname={label}\npkgver={version}\nslot=0\n'.encode(),
                 '.corium/manifest.files':b'engine.txt\nschema/001.sql\n',
                 'engine.txt':b'CI native template', 'schema/001.sql':schema.encode()}
        with tarfile.open(archive,'w:gz') as tf:
            for name,data in files.items():
                item=tarfile.TarInfo(name); item.size=len(data); tf.addfile(item,io.BytesIO(data))
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        cache=self.root/'var/cache/corix/binaries'; cache.mkdir(parents=True,exist_ok=True)
        (cache/(digest+'.tar.gz')).write_bytes(archive.read_bytes())
        signature=signer.signature(archive.read_bytes())
        if bad_signature: signature=b'invalid'
        change={'template_name':label,'pkg_id':'apps/'+label+':0','package_hash':digest,'manifest_hash':digest,
                'developer_signature':base64.b64encode(signature).decode(),'developer_id':self.identity,'handles_tx_types':[]}
        # Put proposal and vote in signed canonical history so replay can derive activation.
        proposal=self.run_core('blockchain_create_transaction propose_app_template '+shlex.quote(json.dumps(change))).stdout.splitlines()[-1]
        self.run_core('blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            proposal_height=db.execute('SELECT block_height FROM transactions WHERE hash=?',(proposal,)).fetchone()[0]
        vote={'proposal_tx_hash':proposal,'vote':'yes'}
        self.run_core('blockchain_create_transaction vote_app_template '+shlex.quote(json.dumps(vote)))
        self.run_core('blockchain_mine_block')
        self.advance_empty_history(proposal_height+99)
        self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"template-ci\"}' >/dev/null")
        self.run_core('blockchain_mine_block')  # Tally after the real 100-block voting window.
        self.advance_empty_history(proposal_height+109)
        self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"template-ci\"}' >/dev/null")
        # The caller mines the activation block, including expected failure cases.

    def advance_empty_history(self, target):
        with sqlite3.connect(self.chain) as db:
            height,timestamp=db.execute('SELECT height,timestamp FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        for next_height in range(height+1,target+1):
            tip=self.add_empty_block(next_height,timestamp=timestamp)
        if target > height:
            with sqlite3.connect(self.chain) as db:
                db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)", (tip+'|'+str(target),))

    def restore_phoenix(self):
        with sqlite3.connect(self.chain) as db:
            db.execute('DELETE FROM blocks'); db.execute('DELETE FROM transactions')
        self.run_core('_internal_import_phoenix_state "$CORIUM_ROOT/snapshot.json"')


    def test_custom_typed_unicode_schema_mine_fresh_replay_and_phoenix(self):
        self.schedule("CREATE TABLE custom_ci(id INTEGER PRIMARY KEY, text_value TEXT, binary_value BLOB); INSERT INTO custom_ci VALUES(1,'中文🙂',X'00ff');")
        self.run_core('blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT * FROM custom_ci').fetchall(),[(1,'中文🙂',b'\x00\xff')])
            height=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
        expected=self.semantic(); self.snapshot(height=height)
        self.run_core('_internal_rebuild_derived_state')
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT * FROM custom_ci').fetchall(),[(1,'中文🙂',b'\x00\xff')])
        self.restore_phoenix()
        recovered=self.semantic()
        self.assertEqual(recovered['application'],expected['application'])
        self.assertEqual({k:v for k,v in recovered['chain'].items() if k not in ('blocks','transactions')},
                         {k:v for k,v in expected['chain'].items() if k not in ('blocks','transactions')})
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT * FROM custom_ci').fetchall(),[(1,'中文🙂',b'\x00\xff')])

    def test_custom_schema_constraint_failure_rolls_back_files_and_databases(self):
        self.schedule('CREATE TABLE constraint_ci(value INTEGER UNIQUE); INSERT INTO constraint_ci VALUES(1); INSERT INTO constraint_ci VALUES(1);')
        before=self.semantic(); self.run_core('blockchain_mine_block',ok=False)
        self.assertEqual(self.semantic(),before)
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='constraint_ci'").fetchone()[0],0)
        self.assertFalse((self.base/'app_templates/apps_ci/1').exists())

    def test_versioned_schema_migration_upgrade_and_phoenix_preserve_rows(self):
        self.schedule("CREATE TABLE versioned_ci(id INTEGER PRIMARY KEY, text_value TEXT); INSERT INTO versioned_ci VALUES(1,'初版🙂');",version=1)
        self.run_core('blockchain_mine_block')
        self.schedule("ALTER TABLE versioned_ci ADD COLUMN revision INTEGER DEFAULT 2; INSERT INTO versioned_ci VALUES(2,'第二版🙂',2);",version=2)
        self.run_core('blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            expected=db.execute('SELECT * FROM versioned_ci ORDER BY id').fetchall()
            height=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
        self.assertEqual(expected,[(1,'初版🙂',2),(2,'第二版🙂',2)])
        self.snapshot(height=height)
        self.run_core('_internal_rebuild_derived_state')
        self.restore_phoenix()
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT * FROM versioned_ci ORDER BY id').fetchall(),expected)

    def test_bad_signature_prevents_custom_schema_activation(self):
        self.schedule('CREATE TABLE forbidden_ci(value TEXT);',bad_signature=True)
        before=self.semantic(); self.run_core('blockchain_mine_block',ok=False)
        self.assertEqual(self.semantic(),before)
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='forbidden_ci'").fetchone()[0],0)
