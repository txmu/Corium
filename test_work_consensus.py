"""Actual native PoW production and crypto units; policy state is a unit fixture.

Full governed activation, peer acceptance and replay require the separate live CI
flow. Unit state seeding below is never used as mainnet governance evidence.
"""
import copy
import json
import hashlib
import os
import shlex
import sqlite3
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_core import Fixture
from work_weight_policy import SCHEMA as WORK_SCHEMA
import work_consensus as work


class NativeWorkConsensusUnits(Fixture):
    def setUp(self):
        self.network_id='test-native-work-v2';super().setUp()
        with sqlite3.connect(self.chain) as db:
            genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        self.policy={'schema':work.SCHEMA,'previous_policy':work.LEGACY,'checkpoint':{'height':0,'hash':genesis},'work_policy':{'schema':WORK_SCHEMA,'network':self.network_id,'genesis':genesis,'activation_height':111,'difficulty_bits':4,'weights':[{'from_height':111,'weight':1000}]}}
        self.engine='a'*64;proposal={'pkg_id':work.PACKAGE,'work_consensus':self.policy,'compute_program_hash':work.policy_hash(self.policy),'verifier_script_hash':work.source_digest()}
        # Signed-header prefix is a fixture, not a claim of governance activation.
        for height in range(1,111):self.add_empty_block(height)
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?)',(self.engine,'propose_new_compute_engine',json.dumps(proposal),'fixture',self.pem,1,1))
            db.execute('INSERT INTO compute_engines VALUES(?,?,?,?,?,1,1)',(self.engine,work.PACKAGE,'fixture',work.policy_hash(self.policy),work.source_digest()))
            db.execute("INSERT OR REPLACE INTO chain_state VALUES('chain_info',?)",(db.execute('SELECT hash FROM blocks WHERE height=110').fetchone()[0]+'|110',))
        self.key_file=self.etc/'identity.key'
        self.previous=self.tip()['hash']

    def tip(self):
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row;return dict(db.execute('SELECT * FROM blocks ORDER BY height DESC LIMIT 1').fetchone())

    def candidate(self,key_file=None):
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            return work.mine(db,self.network_id,key_file or self.key_file,self.previous,111,[])

    def verify(self,block,identity):
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row;return work.verify(db,self.network_id,block,identity)

    def test_native_block_producer_writes_real_work_without_stake_eligibility(self):
        key=ec.generate_private_key(ec.SECP256K1());self.key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        (self.etc/'identity.key.pub').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        self.run_core('blockchain_mine_block')
        tip=self.tip();self.assertEqual(tip['height'],111);self.assertEqual(tip['total_weight'],111000)
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            self.assertIsNone(db.execute('SELECT stake FROM validators WHERE public_key_hash=?',(tip['validator'],)).fetchone())
            block=work.stored(db,tip['hash']);result=work.verify(db,self.network_id,block,tip['hash'])
        self.assertTrue(result['work_verified']);self.assertEqual(result['work_weight'],1000)

    def test_mutations_and_self_reported_weight_cannot_replace_work(self):
        candidate=self.candidate();block=candidate['block'];self.assertTrue(self.verify(block,candidate['hash'])['work_verified'])
        for field,value in [('timestamp',112),('transactions',['b'*64]),('validator','c'*64),('height',112)]:
            changed=copy.deepcopy(block);changed[field]=value
            with self.subTest(field=field),self.assertRaises((ValueError,work.InvalidSignature)):self.verify(changed,candidate['hash'])
        for field,value in [('nonce',block['work']['nonce']+1),('activation','d'*64),('schema','legacy'),('target',1),('weight',2**255)]:
            changed=copy.deepcopy(block);changed['work'][field]=value
            with self.subTest(field=field),self.assertRaises((ValueError,work.InvalidSignature)):self.verify(changed,candidate['hash'])
        with self.assertRaises(ValueError):self.verify({**block,'total_weight':999999999},candidate['hash'])

    def test_mainnet_and_missing_or_expired_governance_never_enable_work(self):
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            self.assertIsNone(work.active(db,'ziokt-main',111))
            with self.assertRaises(ValueError):work.mine(db,'ziokt-main',self.key_file,self.previous,111,[])
            db.execute('UPDATE compute_engines SET is_active=0')
            self.assertIsNone(work.active(db,self.network_id,111))
            with self.assertRaises(ValueError):work.mine(db,self.network_id,self.key_file,self.previous,111,[])

    def test_duplicate_json_and_bounds_reject(self):
        with self.assertRaises(ValueError):work.loads('{"height":1,"height":2}')
        for value in ['NaN','{"value":Infinity}','x'*65537]:
            with self.subTest(value=value[:20]),self.assertRaises(ValueError):work.loads(value)
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            with self.assertRaises(ValueError):work.mine(db,self.network_id,self.key_file,self.previous,111,[],attempts=0)
            with self.assertRaises(ValueError):work.mine(db,self.network_id,self.key_file,self.previous,111,[],start_nonce=2**64)

@unittest.skipUnless(os.environ.get('CORIUM_WORK_LIVE_CHAIN')=='1','Full native activation/replay runs on CI')
class NativeWorkLiveChain(Fixture):
    def setUp(self):
        self.network_id='test-native-work-v2';super().setUp();self.core_timeout=1200

    def test_native_governance_pow_empty_blocks_zero_stake_and_phoenix_replay(self):
        with sqlite3.connect(self.chain) as db:genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        nonce=0
        while not hashlib.sha256((self.network_id+self.identity+str(nonce)+genesis).encode()).hexdigest().startswith('000'):nonce+=1
        proof={'engine_id':'corium/internal-engine-zero-v1','problem_id':genesis,'engine_hash':'BUILT_IN','verifier_hash':'BUILT_IN','proof_data':{'network_id':self.network_id,'submitter_id':self.identity,'nonce':nonce}}
        self.run_core('blockchain_create_transaction submit_math_proof '+shlex.quote(json.dumps(proof))+'; blockchain_mine_block')
        self.run_core('for h in $(seq 2 11); do blockchain_create_transaction set_nickname "{\\\"nickname\\\":\\\"bootstrap-$h\\\"}" >/dev/null || exit; blockchain_mine_block >/dev/null || exit; done')
        with sqlite3.connect(self.chain) as db:anchor=db.execute('SELECT hash FROM blocks WHERE height=11').fetchone()[0]
        policy={'schema':work.SCHEMA,'previous_policy':work.LEGACY,'checkpoint':{'height':11,'hash':anchor},'work_policy':{'schema':WORK_SCHEMA,'network':self.network_id,'genesis':genesis,'activation_height':122,'difficulty_bits':4,'weights':[{'from_height':122,'weight':1000}]}}
        proposal={'pkg_id':work.PACKAGE,'description':'governed native work transition','compute_program_hash':work.policy_hash(policy),'verifier_script_hash':work.source_digest(),'reward_weight':1,'work_consensus':policy}
        engine=self.run_core('blockchain_create_transaction propose_new_compute_engine '+shlex.quote(json.dumps(proposal))).stdout.strip().splitlines()[-1]
        self.run_core('blockchain_mine_block')
        self.run_core('blockchain_create_transaction vote_on_compute_engine '+shlex.quote(json.dumps({'proposal_tx_hash':engine,'vote':'yes'}))+'; blockchain_mine_block')
        self.run_core('for h in $(seq 14 121); do blockchain_create_transaction set_nickname "{\\\"nickname\\\":\\\"native-work-$h\\\"}" >/dev/null || exit; blockchain_mine_block >/dev/null || exit; done')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT count(*) FROM block_work').fetchone()[0],0)
        self.run_core('blockchain_mine_block')  # First governed work block, no pending transactions.
        original_private=(self.etc/'identity.key').read_bytes();original_public=(self.etc/'identity.key.pub').read_bytes()
        key=ec.generate_private_key(ec.SECP256K1())
        (self.etc/'identity.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        (self.etc/'identity.key.pub').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        self.run_core('blockchain_mine_block')  # Native miner has no stake entry.
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row;tip=db.execute('SELECT * FROM blocks WHERE height=123').fetchone();self.assertIsNotNone(tip)
            self.assertEqual(tip['total_weight'],123000);self.assertEqual(db.execute('SELECT count(*) FROM block_work').fetchone()[0],2)
            self.assertIsNone(db.execute('SELECT stake FROM validators WHERE public_key_hash=?',(tip['validator'],)).fetchone())
            self.assertTrue(work.verify(db,self.network_id,work.stored(db,tip['hash']),tip['hash'])['work_verified'])
        # Restore the existing governance identity for authorized snapshot signing.
        (self.etc/'identity.key').write_bytes(original_private);(self.etc/'identity.key.pub').write_bytes(original_public)
        snapshot=self.snapshot('native-work-rebuilt.json',height=123)
        self.assertEqual(len(snapshot['state']['chain_tables']['block_work']),2)
        # Phoenix intentionally exports derived state without block history.
        # Its independently verified canonical anchor must be the accepted tip.
        self.assertEqual(snapshot['recovery_anchor']['height'],123)
        self.assertEqual(snapshot['recovery_anchor']['block_hash'],tip['hash'])

if __name__=='__main__':unittest.main()
