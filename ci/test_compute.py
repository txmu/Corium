"""All implemented engine branches: Engine Zero, GIMPS and executable Mods."""
import hashlib
import json
import shlex
import sqlite3
from test_core import Fixture
import test_core

class Compute(Fixture):
    put_transaction=test_core.CoreTests.put_transaction
    validate_transaction=test_core.CoreTests.validate_transaction

    def test_engine_zero_task_proof_binding_and_native_submission(self):
        task=self.run_core('_get_current_compute_task').stdout.strip().splitlines()[-1]
        fields=task.split('|')
        self.assertEqual(fields[0],'corium/internal-engine-zero-v1')
        problem,target,difficulty=fields[1:4]
        self.assertEqual(problem,target); self.assertEqual(fields[4:6],['BUILT_IN','BUILT_IN'])
        nonce=0
        while not hashlib.sha256(('default'+self.identity+str(nonce)+target).encode()).hexdigest().startswith('0'*int(difficulty)):
            nonce+=1
            self.assertLess(nonce,1000000)
        proof={'engine_id':fields[0],'problem_id':problem,'engine_hash':'BUILT_IN','verifier_hash':'BUILT_IN',
               'task_data':target+'|'+difficulty,'proof_data':{'nonce':str(nonce),'submitter_id':self.identity,'network_id':'default'}}
        path=self.root/'proof.json'; path.write_text(json.dumps(proof))
        self.run_core('_internal_compute_submit '+str(path))
        with sqlite3.connect(self.chain) as db:
            tx=db.execute("SELECT hash FROM transactions WHERE type='submit_math_proof'").fetchone()[0]
        self.validate_transaction(tx)
        forged=dict(proof['proof_data'],submitter_id='f'*64)
        tx=self.put_transaction('submit_math_proof',dict(proof,proof_data=forged),99)
        self.validate_transaction(tx,ok=False)

    def test_gimps_native_task_progression_exhaustion_and_lucas_lehmer(self):
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO compute_engines VALUES(?,?,?,?,?,?,?)',('gimps-ci','corium/built-in-gimps','small Mersenne task','a'*64,'b'*64,1,100))
            db.execute('INSERT INTO problem_sets VALUES(?,?,?,?)',('set-ci','gimps-ci',json.dumps({'start_exponent':5,'end_exponent':7}),0))
        self.assertIn('gimps-ci|5|5|',self.run_core('_get_current_compute_task').stdout)
        # Run the native sandbox with an actual Lucas-Lehmer calculation, not a canned answer.
        program='import json; p=5; m=(1<<p)-1; s=4\nfor _ in range(p-2): s=(s*s-2)%m\nprint(json.dumps({"exponent":p,"residue":s,"is_prime":s==0}))'
        result=self.run_core('_execute_mod_in_sandbox corium/built-in-gimps contribution_compute /usr/bin/python3 -c '+shlex.quote(program))
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]),{'exponent':5,'residue':0,'is_prime':True})
        self.put_transaction('submit_math_proof',{'engine_id':'gimps-ci','problem_id':'5','proof_data':{'residue':0}},1)
        self.assertEqual(self.run_core("_internal_generate_gimps_task gimps-ci set-ci '{\"start_exponent\":5,\"end_exponent\":7}'").stdout.strip(),'6|6')
        self.put_transaction('submit_math_proof',{'engine_id':'gimps-ci','problem_id':'7','proof_data':{}},2)
        self.run_core("_internal_generate_gimps_task gimps-ci set-ci '{\"start_exponent\":5,\"end_exponent\":7}'",ok=False)

    def test_custom_mod_executable_manifest_scheduler_and_native_run(self):
        repo=self.root/'repo/compute/sum'; repo.mkdir(parents=True)
        (repo/'sum.build').write_text('pkgname=sum\npkgver=1\nslot=0\ncorix_mod_type=contribution_compute\nexecutable=sum-engine\nmemory_limit_mb=128\ncpu_time_limit_s=5\nnetwork_access=none\n')
        configs=self.etc/'repos.conf.d'; configs.mkdir(); (configs/'local.conf').write_text('type=local\npath='+str(self.root/'repo')+'\n')
        program=self.root/'usr/bin/sum-engine'; program.parent.mkdir(parents=True)
        program.write_text('#!/bin/bash\nif [ "$1" = get-next-task ]; then echo "sum-10|10"; else python3 -c "import sys; print(sum(range(int(sys.argv[1])+1)))" "$1"; fi\n'); program.chmod(0o755)
        installed=self.base/'installed/compute_sum-0'; installed.mkdir(parents=True)
        (installed/'files').write_text('usr/bin/sum-engine\n'); (installed/'version').write_text('1\n')
        digest=self.run_core('_p2p_upload_file '+str(program)).stdout.splitlines()[-1]
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO compute_engines VALUES(?,?,?,?,?,?,?)',('sum-ci','compute/sum:0','sum engine',digest,digest,1,100))
            db.execute('INSERT INTO problem_sets VALUES(?,?,?,?)',('sum-set','sum-ci','{}',0))
        self.assertIn('sum-ci|sum-10|10|',self.run_core('_get_current_compute_task').stdout)
        self.assertEqual(self.run_core('_execute_mod_in_sandbox compute/sum:0 contribution_compute '+str(program)+' 10').stdout.strip(),'55')
        self.run_core('_internal_compute_run sum-ci')

    def test_compute_missing_inactive_engine_and_malformed_proof_fail_closed(self):
        self.run_core('_internal_compute_run nonexistent',ok=False)
        self.run_core('_internal_compute_submit "$CORIUM_ROOT/missing.json"',ok=False)
        path=self.root/'invalid.json'; path.write_text('{}')
        before=self.semantic(); self.run_core('_internal_compute_submit '+str(path),ok=False)
        self.assertEqual(self.semantic(),before)
