"""Original signed transaction validation; never a mock verifier success."""
import hashlib,json,sqlite3
from test_core import Fixture


class EngineProofBoundary(Fixture):
    def submit(self,engine,nonce,challenge):
        payload={'engine_id':engine,'problem_id':challenge,'engine_hash':'a'*64,'verifier_hash':'b'*64,
                 'proof_data':{'nonce':str(nonce),'network_id':'default','submitter_id':self.identity}}
        raw=json.dumps(payload,separators=(',',':'))
        body='{"type":"submit_math_proof","data":'+raw+',"timestamp":1}'
        digest=hashlib.sha256(body.encode()).hexdigest()
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,NULL)',(digest,'submit_math_proof',raw,self.sign(body),self.pem,1))
        return digest

    def test_exact_builtin_pow_and_prefix_lookalikes(self):
        with sqlite3.connect(self.chain) as db:
            challenge=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        nonce=0
        while not hashlib.sha256(('default'+self.identity+str(nonce)+challenge).encode()).hexdigest().startswith('000'):nonce+=1
        for engine in ('corium/internal-engine-zero','corium/internal-engine-zero-v2','corium/internal-engine-zero-v1-forged'):
            digest=self.submit(engine,nonce,challenge)
            self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+digest+' "" "" 1 tracker cache',ok=False)
        valid=self.submit('corium/internal-engine-zero-v1',nonce,challenge)
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+valid+' "" "" 1 tracker cache')
        wrong=nonce+1
        while hashlib.sha256(('default'+self.identity+str(wrong)+challenge).encode()).hexdigest().startswith('000'):wrong+=1
        invalid=self.submit('corium/internal-engine-zero-v1',wrong,challenge)
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+invalid+' "" "" 1 tracker cache',ok=False)

    def test_registered_engine_still_requires_active_hashes(self):
        with sqlite3.connect(self.chain) as db:
            challenge=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
            db.execute('INSERT INTO compute_engines VALUES(?,?,?,?,?,0,1)',('e'*64,'compute/openci:0','test','a'*64,'b'*64))
        digest=self.submit('e'*64,0,challenge)
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+digest+' "" "" 1 tracker cache',ok=False)
        with sqlite3.connect(self.chain) as db:db.execute('UPDATE compute_engines SET is_active=1')
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+digest+' "" "" 1 tracker cache')
        with sqlite3.connect(self.chain) as db:db.execute('UPDATE compute_engines SET verifier_script_hash=?',('c'*64,))
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+digest+' "" "" 1 tracker cache',ok=False)

    def test_builtin_challenge_uses_signed_engine_without_problem_set_alias(self):
        with sqlite3.connect(self.chain) as db:
            challenge=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
        nonce=0
        while not hashlib.sha256(('default'+self.identity+str(nonce)+challenge).encode()).hexdigest().startswith('000'):nonce+=1
        digest=self.submit('corium/internal-engine-zero-v1',nonce,challenge)
        challenger='c'*64
        with sqlite3.connect(self.chain) as db:
            payload=json.loads(db.execute('SELECT data FROM transactions WHERE hash=?',(digest,)).fetchone()[0])
            db.execute('INSERT INTO pending_proofs VALUES(?,?,?,?,100)',(challenge,digest,self.identity,json.dumps(payload['proof_data'])))
            db.execute('INSERT INTO challenges VALUES(?,?,?,?,?)',('d'*64,digest,challenger,'{}','pending'))
            db.execute('INSERT INTO contribution_scores VALUES(?,500,0)',(challenger,))
            self.assertEqual(db.execute('SELECT count(*) FROM problem_sets').fetchone()[0],0)
        self.run_core('_resolve_proofs_and_challenges_at_height 1')
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT status FROM challenges').fetchone()[0],'rejected')
            self.assertEqual(db.execute('SELECT score FROM contribution_scores WHERE user_id=?',(challenger,)).fetchone()[0],450)
            self.assertEqual(db.execute('SELECT count(*) FROM pending_proofs').fetchone()[0],1)
