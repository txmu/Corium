"""Native DNA replay uses only its genesis-authority signed archive state."""
import hashlib,json,sqlite3
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from test_core import Fixture
import dna_protocol as DNA
import recovery_consensus as Recovery
import work_consensus as Work

class DNAReplayAnchorTests(Fixture):
    def setUp(self):
        self.network_id='ziokt-dna-side-20261024';super().setUp()
        (self.etc/'genesis.json').chmod(0o600)
        for height in range(1,785):self.add_empty_block(height,signature='00' if height==51 else None)
        state=self.semantic();self.baseline=self.etc/'recovery-state.json';self.baseline.write_bytes(DNA.encoded(state));self.baseline.chmod(0o600)
        with sqlite3.connect(self.chain) as db:
            genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
            anchor=db.execute('SELECT hash FROM blocks WHERE height=784').fetchone()[0]
            db.execute("INSERT OR REPLACE INTO chain_state VALUES('chain_info',?)",(anchor+'|784',))
            db.execute("INSERT OR REPLACE INTO chain_state VALUES('last_processed_height','784')")
        declaration={'schema':Recovery.SCHEMA,'network':self.network_id,'protocol':Recovery.SIDE,
            'checkpoint':{'height':784,'hash':anchor},'initial_state_root':hashlib.sha256(DNA.encoded(state)).hexdigest(),
            'legacy_archive_root':'a'*64,'genesis_sha256':hashlib.sha256((self.etc/'genesis.json').read_bytes()).hexdigest(),
            'verifier_source_sha256':Work.source_digest(),'work_policy':{'schema':'corium.work-weight-policy.v1','network':self.network_id,'genesis':genesis,'activation_height':785,'difficulty_bits':4,'weights':[{'from_height':785,'weight':1000}]},'authority_public_key':self.pem}
        declaration['signature']=self.key.sign(Recovery.signing_bytes(declaration),ec.ECDSA(hashes.SHA256())).hex()
        (self.etc/'recovery.json').write_bytes(DNA.encoded(declaration));(self.etc/'recovery.json').chmod(0o600)
        self.run_core('blockchain_mine_block; blockchain_mine_block')

    def test_signed_archive_baseline_and_post_anchor_native_work_replay(self):
        replay=self.root/'replayed';replay.mkdir()
        self.run_core('_internal_replay_chain_state 786 "'+str(replay)+'"')
        with sqlite3.connect(replay/'chain.db') as db,sqlite3.connect(self.chain) as source:
            self.assertEqual(db.execute('SELECT height,hash FROM blocks ORDER BY height').fetchall(),source.execute('SELECT height,hash FROM blocks ORDER BY height').fetchall())
            self.assertEqual(db.execute("SELECT value FROM chain_state WHERE key='last_processed_height'").fetchone()[0],'786')
            self.assertEqual(db.execute('SELECT count(*) FROM block_work').fetchone()[0],2)

    def test_changed_baseline_and_wrong_authority_are_rejected(self):
        original=self.baseline.read_bytes();state=json.loads(original);state['chain']['validators'][0]['stake']+=1
        self.baseline.write_bytes(DNA.encoded(state));replay=self.root/'rejected';replay.mkdir()
        self.run_core('_internal_replay_chain_state 786 "'+str(replay)+'"',False)
        self.baseline.write_bytes(original);declaration=json.loads((self.etc/'recovery.json').read_bytes());declaration['signature']='00';(self.etc/'recovery.json').write_bytes(DNA.encoded(declaration))
        self.run_core('_internal_replay_chain_state 786 "'+str(replay)+'"',False)
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT MAX(height) FROM blocks').fetchone()[0],786)
