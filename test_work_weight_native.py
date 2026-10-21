"""Actual native parent state, secp256k1 signatures and work-byte binding.

These tests do not activate a consensus version or admit v2 blocks to v108.
"""
import copy
import hashlib
import json
import sqlite3

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

from test_core import Fixture
from work_weight_policy import SCHEMA, PolicyError, work_digest
from work_weight_native import candidate, context, inspect_database, signing_bytes, verify_candidate


class NativeWorkBindingTests(Fixture):
    def setUp(self):
        self.network_id='test-work-binding'
        super().setUp()
        with sqlite3.connect(self.chain) as db:
            row=db.execute('SELECT height,hash,timestamp,total_weight FROM blocks WHERE height=0').fetchone()
        self.parent=dict(zip(('height','hash','timestamp','total_weight'),row))
        self.policy={'schema':SCHEMA,'network':self.network_id,'genesis':row[1],'activation_height':1,
                     'difficulty_bits':4,'weights':[{'from_height':1,'weight':1000}]}

    def make(self,**changes):
        args={'parent':self.parent,'timestamp':1,'transactions':[],'private_key':self.key,
              'network':self.network_id,'genesis':self.policy['genesis'],'attempts':10000}
        return candidate(self.policy,**{**args,**changes})

    def verify(self,block,**changes):
        args={'parent':self.parent,'network':self.network_id,'genesis':self.policy['genesis']}
        return verify_candidate(self.policy,block,**{**args,**changes})

    def test_real_native_parent_and_signed_transaction_candidate_do_not_modify_chain(self):
        tx=self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"Work binding\"}'").stdout.strip().splitlines()[-1]
        self.assertEqual(len(tx),64)
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+tx+' "" "" 1 tracker cache')
        block=self.make(transactions=[tx])
        before=self.semantic()
        result=inspect_database(self.chain,self.policy,block,self.network_id)
        self.assertTrue(result['native_parent_observed']);self.assertTrue(result['native_signature_verified'])
        self.assertTrue(result['canonical_header_verified']);self.assertEqual(result['total_weight'],1000)
        for key in ('block_fully_validated','ledger_modified','network_activated','transactions_validated','native_consensus_accepted','finalized'):
            self.assertFalse(result[key],key)
        self.assertEqual(before,self.semantic())

    def test_every_consensus_header_field_is_bound(self):
        block=self.make()
        for key,value in [('timestamp',2),('height',2),('previous_hash','f'*64),('transactions',['a'*64]),('policy','b'*64),('network','other')]:
            changed=copy.deepcopy(block);changed['header'][key]=value
            with self.subTest(key=key),self.assertRaises(PolicyError):self.verify(changed)
        changed=copy.deepcopy(block);changed['header']['unused']=True
        with self.assertRaises(PolicyError):self.verify(changed)
        with self.assertRaises(PolicyError):self.verify({**block,'version':2})

    def test_valid_alternative_nonce_still_needs_matching_native_signature(self):
        block=self.make();changed=copy.deepcopy(block)
        nonce=block['work']['nonce']+1
        while int(work_digest(self.policy,context(block['header']),nonce),16)>=2**252:nonce+=1
        changed['work']['nonce']=nonce
        changed['hash']=hashlib.sha256(signing_bytes(changed['header'],changed['work'])).hexdigest()
        with self.assertRaisesRegex(PolicyError,'signature rejected'):self.verify(changed)
        changed=copy.deepcopy(block)
        changed['signature']=ec.generate_private_key(ec.SECP256K1()).sign(signing_bytes(changed['header'],changed['work']),ec.ECDSA(hashes.SHA256())).hex()
        with self.assertRaisesRegex(PolicyError,'signature rejected'):self.verify(changed)

    def test_network_parent_and_weight_cannot_be_supplied_by_remote_candidate(self):
        block=self.make()
        with self.assertRaises(PolicyError):self.verify(block,network='ziokt-main')
        with self.assertRaises(PolicyError):self.verify(block,genesis='e'*64)
        changed=copy.deepcopy(block);changed['header']['previous_hash']='d'*64
        with self.assertRaises(PolicyError):inspect_database(self.chain,self.policy,changed,self.network_id)
        forged={**block,'total_weight':1000000}
        with self.assertRaises(PolicyError):inspect_database(self.chain,self.policy,forged,self.network_id)

    def test_bounded_work_and_header_integer_rejections(self):
        for changes in ({'timestamp':True},{'timestamp':-1},{'transactions':['a'*64,'a'*64]},{'transactions':['a'*64]*201},{'attempts':0},{'start_nonce':2**64-1,'attempts':2}):
            with self.subTest(changes=changes),self.assertRaises(PolicyError):self.make(**changes)
        self.policy={**self.policy,'difficulty_bits':256}
        with self.assertRaisesRegex(PolicyError,'bounded attempt range'):self.make(attempts=1)

    def test_inspector_reads_parent_weight_from_actual_native_chain(self):
        self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"Original PoS\"}'; blockchain_mine_block")
        with sqlite3.connect(self.chain) as db:
            row=db.execute('SELECT height,hash,timestamp,total_weight FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        self.assertEqual(row[0],1);self.assertEqual(row[3],1000)
        self.parent=dict(zip(('height','hash','timestamp','total_weight'),row))
        block=self.make(timestamp=row[2]+1)
        result=inspect_database(self.chain,self.policy,block,self.network_id)
        self.assertEqual(result['total_weight'],2000)
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT max(height) FROM blocks').fetchone()[0],1)
