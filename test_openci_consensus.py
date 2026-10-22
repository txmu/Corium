"""Native quorum predicate units plus opt-in actual 133-block governance chain.

Signed fixture receipts below are cryptographic test inputs, not OCI execution
proof. The separate Controller/Runner integration supplies real execution receipts.
"""
import copy
import hashlib
import json
import os
import shlex
import sqlite3
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from test_core import Fixture
import openci_consensus as consensus


def policy_for(genesis,beneficiary,activation=111):
    keys=[Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()]
    workers=[{'id':'builder' if i==0 else 'verifier','public_key':key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex(),'failure_domain':'domain'+str(i),'pool':'community' if i==0 else 'trusted'} for i,key in enumerate(keys)]
    source={'object':'cf1-'+'a'*64,'digest':'sha256:'+'b'*64}
    program={'image':'python@sha256:'+'c'*64,'argv':['python','-c','print(1)'],'arch':'x86_64','outputs':['result.json'],'cpu':1,'memory_mb':128,'timeout':30}
    bounty={'name':'build-release','beneficiary':beneficiary,'anchor':genesis,'source':source,'program':program}
    policy={'schema':consensus.SCHEMA,'network':'test-openci-settlement','genesis':genesis,'activation_height':activation,'expiry_height':1000,'threshold':2,'workers':workers,'bounties':[bounty]}
    program['argv'].append(consensus.claim_token(policy,bounty));return policy,keys


def proof_for(policy,keys,engine):
    bounty=policy['bounties'][0];receipts=[]
    for index,(key,worker) in enumerate(zip(keys,policy['workers'])):
        task={'id':'replica'+str(index),'needs':[],'pool':worker['pool'],'worker':worker['id'],'attempts':1,**bounty['program']}
        result={'exit_code':0,'artifact':{'object':'cf1-'+'d'*64,'digest':'sha256:'+'e'*64},'logs':{'object':'cf1-'+'f'*64,'digest':'sha256:'+'1'*64}}
        statement={'schema':'openci.worker-receipt.v1','worker':worker['id'],'pipeline':'2'*64,'task':task['id'],'attempt':1,'source':bounty['source'],'task_digest':'sha256:'+hashlib.sha256(consensus.canonical(task,ascii=True)).hexdigest(),'lease_digest':'sha256:'+str(index+3)*64,'result':result}
        envelope={'schema':'ziokt.signed.v1','domain':consensus.DOMAIN,'public_key':worker['public_key'],'payload':statement,'signature':key.sign((consensus.DOMAIN+'\n').encode()+consensus.canonical(statement)).hex()}
        receipts.append({'task':task,'attestation':envelope})
    return {'engine_id':engine,'problem_id':consensus.problem(policy,bounty['name']),'engine_hash':consensus.policy_digest(policy),'verifier_hash':consensus.source_digest(),'proof_data':{'schema':'corium.openci-quorum-proof.v1','receipts':receipts}}


class NativeOpenCIUnits(Fixture):
    def setUp(self):
        self.network_id='test-openci-settlement';super().setUp()
        with sqlite3.connect(self.chain) as db:genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        self.policy,self.keys=policy_for(genesis,self.identity);self.engine='4'*64
        self.proposal={'pkg_id':consensus.PACKAGE,'description':'governed test bounty','compute_program_hash':consensus.policy_digest(self.policy),'verifier_script_hash':consensus.source_digest(),'reward_weight':2,'openci_policy':self.policy}
        # Unit fixture state only; NativeOpenCILiveChain tests genuine governance.
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?)',(self.engine,'propose_new_compute_engine',json.dumps(self.proposal),'fixture',self.pem,1,1))
            db.execute('INSERT INTO compute_engines VALUES(?,?,?,?,?,1,2)',(self.engine,consensus.PACKAGE,'fixture',consensus.policy_digest(self.policy),consensus.source_digest()))
        self.payload=proof_for(self.policy,self.keys,self.engine)

    def check(self,payload=None,sender=None,network=None,height=111):
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            return consensus.validate_claim(db,network or self.network_id,payload or self.payload,sender or self.identity,height)

    def test_exact_quorum_and_recipient_binding(self):
        result=self.check();self.assertEqual(result['reward'],200);self.assertFalse(result['hardware_independence_verified'])
        for changes in ({'sender':'5'*64},{'network':'ziokt-main'},{'height':110},{'height':1000}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.check(**changes)
        for change in ('signature','task','source','artifact','duplicate','missing'):
            payload=copy.deepcopy(self.payload);entries=payload['proof_data']['receipts']
            if change=='signature':entries[0]['attestation']['signature']='0'*128
            if change=='task':entries[0]['task']['argv'][0]='evil'
            if change=='source':entries[0]['attestation']['payload']['source']['digest']='sha256:'+'0'*64
            if change=='artifact':entries[1]['attestation']['payload']['result']['artifact']['digest']='sha256:'+'0'*64
            if change=='duplicate':entries[1]=copy.deepcopy(entries[0])
            if change=='missing':entries.pop()
            with self.subTest(change=change),self.assertRaises((ValueError,consensus.InvalidSignature)):self.check(payload)

    def test_governance_key_hash_domain_and_program_changes_reject(self):
        for change in ('inactive','engine_hash','verifier_hash','domain','reward_weight'):
            with sqlite3.connect(self.chain) as db:
                if change=='reward_weight':db.execute('UPDATE compute_engines SET reward_weight=3')
                if change=='inactive':db.execute('UPDATE compute_engines SET is_active=0')
                if change=='engine_hash':db.execute('UPDATE compute_engines SET compute_program_hash=?',('0'*64,))
                if change=='verifier_hash':db.execute('UPDATE compute_engines SET verifier_script_hash=?',('0'*64,))
                if change=='domain':
                    value=copy.deepcopy(self.proposal);value['openci_policy']['workers'][1]['failure_domain']='domain0';db.execute('UPDATE transactions SET data=? WHERE hash=?',(json.dumps(value),self.engine))
            with self.subTest(change=change),self.assertRaises(ValueError):self.check()
            with sqlite3.connect(self.chain) as db:
                db.execute('UPDATE compute_engines SET is_active=1,reward_weight=2,compute_program_hash=?,verifier_script_hash=?',(consensus.policy_digest(self.policy),consensus.source_digest()));db.execute('UPDATE transactions SET data=? WHERE hash=?',(json.dumps(self.proposal),self.engine))

    def pending(self):
        tx='6'*64
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?)',(tx,'submit_math_proof',json.dumps(self.payload),'fixture',self.pem,111,111))
            db.execute('INSERT INTO pending_proofs VALUES(?,?,?,?,?)',(self.payload['problem_id'],tx,self.identity,'null',121))
        return tx

    def test_existing_pending_claim_cannot_be_admitted_again(self):
        tx=self.pending()
        with self.assertRaises(ValueError):self.check()
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            self.assertEqual(consensus.validate_claim(db,self.network_id,self.payload,self.identity,111,accepted_tx=tx)['reward'],200)
            with self.assertRaises(ValueError):consensus.validate_claim(db,self.network_id,self.payload,self.identity,111,accepted_tx='7'*64)

    def test_atomic_settlement_and_double_redemption(self):
        tx=self.pending()
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');result=consensus.settle(db,self.network_id,tx,121)
        self.assertEqual(result['contribution_score'],200);self.assertFalse(result['proposal_weight_changed'])
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row;self.assertTrue(consensus.settle(db,self.network_id,tx,122)['duplicate'])
            self.assertEqual(db.execute('SELECT score FROM contribution_scores WHERE user_id=?',(self.identity,)).fetchone()[0],200)
            self.assertEqual(db.execute('SELECT count(*) FROM completed_compute_tasks').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM pending_proofs').fetchone()[0],0)

    def test_early_challenged_and_overflow_settlements_fail_without_partial_credit(self):
        tx=self.pending()
        with sqlite3.connect(self.chain) as db:
            db.row_factory=sqlite3.Row
            with self.assertRaises(ValueError):consensus.settle(db,self.network_id,tx,120)
            db.execute('INSERT INTO challenges VALUES(?,?,?,?,?)',('7'*64,tx,self.identity,'{}','pending'))
            with self.assertRaises(ValueError):consensus.settle(db,self.network_id,tx,121)
            db.execute("UPDATE challenges SET status='rejected'");db.execute('INSERT INTO contribution_scores VALUES(?,?,?)',(self.identity,2**63-100,0))
            with self.assertRaises(ValueError):consensus.settle(db,self.network_id,tx,121)
            self.assertEqual(db.execute('SELECT count(*) FROM completed_compute_tasks').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM pending_proofs').fetchone()[0],1)


class NativeOpenCIAdmission(Fixture):
    def setUp(self):
        self.network_id='test-openci-settlement';super().setUp()
        with sqlite3.connect(self.chain) as db:
            genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
            db.execute('INSERT INTO contribution_scores VALUES(?,100,0)',(self.identity,))
        self.policy,self.keys=policy_for(genesis,self.identity)
        self.proposal={'pkg_id':consensus.PACKAGE,'description':'native admission','compute_program_hash':consensus.policy_digest(self.policy),'verifier_script_hash':consensus.source_digest(),'reward_weight':2,'openci_policy':self.policy}

    def test_real_proposal_and_vote_do_not_activate_before_governance_window(self):
        engine=self.run_core('blockchain_create_transaction propose_new_compute_engine '+shlex.quote(json.dumps(self.proposal))).stdout.strip().splitlines()[-1]
        self.run_core('blockchain_mine_block')
        self.run_core('blockchain_create_transaction vote_on_compute_engine '+shlex.quote(json.dumps({'proposal_tx_hash':engine,'vote':'yes'}))+'; blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT max(height) FROM blocks').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT is_active FROM compute_engines WHERE engine_id=?',(engine,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM completed_compute_tasks').fetchone()[0],0)

    def test_invalid_policy_commitment_rejects_real_native_block(self):
        proposal=copy.deepcopy(self.proposal);proposal['verifier_script_hash']='0'*64
        self.run_core('blockchain_create_transaction propose_new_compute_engine '+shlex.quote(json.dumps(proposal)))
        self.run_core('blockchain_mine_block',ok=False)
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT max(height) FROM blocks').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM compute_engines').fetchone()[0],0)


@unittest.skipUnless(os.environ.get('CORIUM_OPENCI_LIVE_CHAIN')=='1','Actual long native governance chain runs on CI')
class NativeOpenCILiveChain(Fixture):
    def test_native_proposal_vote_activation_contribution_settlement_and_replay(self):
        with sqlite3.connect(self.chain) as db:
            genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        # Earn proposal eligibility through real original Engine Zero work and
        # its native challenge window; no preseeded score can survive replay.
        nonce=0
        while not hashlib.sha256((self.network_id+self.identity+str(nonce)+genesis).encode()).hexdigest().startswith('000'):nonce+=1
        bootstrap={'engine_id':'corium/internal-engine-zero-v1','problem_id':genesis,'engine_hash':'BUILT_IN','verifier_hash':'BUILT_IN','proof_data':{'network_id':self.network_id,'submitter_id':self.identity,'nonce':nonce}}
        self.core_timeout=900
        self.run_core('blockchain_create_transaction submit_math_proof '+shlex.quote(json.dumps(bootstrap))+'; blockchain_mine_block')
        self.run_core('for h in $(seq 2 11); do blockchain_create_transaction set_nickname "{\\\"nickname\\\":\\\"bootstrap-$h\\\"}" >/dev/null || exit; blockchain_mine_block >/dev/null || exit; done')
        # No score row exists before Engine Zero settles. Earlier IBC queue
        # entries therefore cannot debit that future reward. Capture both
        # canonical balance and already processed postage at the reward boundary.
        with sqlite3.connect(self.chain) as db:
            bootstrap_score=db.execute('SELECT score FROM contribution_scores WHERE user_id=?',(self.identity,)).fetchone()[0]
            bootstrap_postage=db.execute("SELECT COALESCE(sum(q.postage),0) FROM ibc_outgoing_queue q JOIN transactions t ON t.hash=q.source_tx_hash WHERE t.type='ibc_dispatch' AND t.block_height IS NOT NULL AND t.public_key=?",(self.pem,)).fetchone()[0]
        self.assertEqual(bootstrap_score,100)
        policy,keys=policy_for(genesis,self.identity,activation=122)
        real_payload=None
        if os.environ.get('CORIUM_OPENCI_OCI')=='1':
            from native_receipts import execute
            policy,real_payload=execute(genesis,self.identity,122)
        proposal={'pkg_id':consensus.PACKAGE,'description':'real native governance test','compute_program_hash':consensus.policy_digest(policy),'verifier_script_hash':consensus.source_digest(),'reward_weight':2,'openci_policy':policy}
        self.core_timeout=900
        engine=self.run_core('blockchain_create_transaction propose_new_compute_engine '+shlex.quote(json.dumps(proposal))).stdout.strip().splitlines()[-1]
        self.run_core('blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT is_active FROM compute_engines WHERE engine_id=?',(engine,)).fetchone()[0],0)
        self.run_core('blockchain_create_transaction vote_on_compute_engine '+shlex.quote(json.dumps({'proposal_tx_hash':engine,'vote':'yes'}))+'; blockchain_mine_block')
        self.run_core('for h in $(seq 14 122); do blockchain_create_transaction set_nickname "{\\"nickname\\":\\"native-bounty-$h\\"}" >/dev/null || exit; blockchain_mine_block >/dev/null || exit; done')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT is_active FROM compute_engines WHERE engine_id=?',(engine,)).fetchone()[0],1)
        payload=({**real_payload,'engine_id':engine} if real_payload else proof_for(policy,keys,engine))
        tx=self.run_core('blockchain_create_transaction submit_math_proof '+shlex.quote(json.dumps(payload))).stdout.strip().splitlines()[-1]
        self.run_core('blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM completed_compute_tasks WHERE engine_id=?',(engine,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM completed_compute_tasks WHERE engine_id=?',('corium/internal-engine-zero-v1',)).fetchone()[0],1)
            postage=db.execute("SELECT COALESCE(sum(q.postage),0) FROM ibc_outgoing_queue q JOIN transactions t ON t.hash=q.source_tx_hash WHERE t.type='ibc_dispatch' AND t.block_height IS NOT NULL AND t.public_key=?",(self.pem,)).fetchone()[0]
            self.assertGreater(postage,0)
            self.assertEqual(db.execute('SELECT score FROM contribution_scores WHERE user_id=?',(self.identity,)).fetchone()[0],bootstrap_score-(postage-bootstrap_postage))
        self.run_core('for h in $(seq 124 133); do blockchain_create_transaction set_nickname "{\\"nickname\\":\\"native-settle-$h\\"}" >/dev/null || exit; blockchain_mine_block >/dev/null || exit; done')
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT proof_tx_hash FROM completed_compute_tasks WHERE engine_id=?',(engine,)).fetchone()[0],tx)
            postage=db.execute("SELECT COALESCE(sum(q.postage),0) FROM ibc_outgoing_queue q JOIN transactions t ON t.hash=q.source_tx_hash WHERE t.type='ibc_dispatch' AND t.block_height IS NOT NULL AND t.public_key=?",(self.pem,)).fetchone()[0]
            expected_score=bootstrap_score+200-(postage-bootstrap_postage)
            self.assertEqual(db.execute('SELECT score FROM contribution_scores WHERE user_id=?',(self.identity,)).fetchone()[0],expected_score)
            self.assertEqual(db.execute('SELECT count(*) FROM pending_proofs').fetchone()[0],0)
        # Native Phoenix export independently rebuilds from signed history.
        snapshot=self.snapshot('openci-rebuilt.json',height=133)
        self.assertEqual(next(r['score'] for r in snapshot['state']['chain_tables']['contribution_scores'] if r['user_id']==self.identity),expected_score)

    def setUp(self):
        self.network_id='test-openci-settlement';super().setUp()

if __name__=='__main__':unittest.main()
