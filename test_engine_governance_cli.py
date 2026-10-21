"""Native CLI dispatch/failure units and genuine signed pending transactions.

No governance activation, owner approval or consensus validation is bypassed.
"""
from contextlib import closing
import json,os,re,shlex,sqlite3,subprocess,tempfile,unittest
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from test_gateway import SOURCE
from test_core import Fixture


def functions():
    source=Path(SOURCE).read_text()
    return '\n'.join(re.search(r'^'+name+r'\(\) \{.*?^\}',source,re.M|re.S).group() for name in ('_internal_governance_propose_engine','_internal_governance_vote_engine'))


class EngineDispatchUnits(unittest.TestCase):
    def invoke(self,command,submission):
        # Controlled submitter is a unit fixture, never native consensus evidence.
        with tempfile.TemporaryDirectory() as area:
            script='msg(){ :; }; info(){ :; }; error(){ printf "%s\\n" "$*" >&2; }; _apply_theme(){ printf "%s\\n" "$*"; }; usage_governance(){ :; };\n'+functions()+'\nblockchain_create_transaction(){ '+submission+'; };\n'+command
            return subprocess.run(['bash','-c',script],cwd=area,capture_output=True,text=True,timeout=10)

    def test_dispatch_does_not_inherit_global_transaction_type(self):
        result=self.invoke('vote_tx_type=unrelated_action; _internal_governance_vote_engine '+('a'*64)+' yes','test "$1" = vote_on_compute_engine || return 9; printf "%064d\\n" 0')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('confirmation pending',result.stdout)

    def test_failure_or_nonhash_output_never_reports_submission(self):
        for function,args in [('_internal_governance_vote_engine',('a'*64)+' yes'),('_internal_governance_propose_engine','desc compute/openci:0 '+('b'*64)+' '+('c'*64)+' 1')]:
            for submitter in ['printf "%064d\\n" 0; return 1','printf "not-a-transaction\\n"']:
                result=self.invoke(function+' '+args,submitter)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('confirmation pending',result.stdout)

    def test_no_vote_remains_native_abstention_without_transaction(self):
        result=self.invoke('_internal_governance_vote_engine '+('a'*64)+' no','return 91')
        self.assertEqual(result.returncode,0,result.stderr)


class SignedEngineSubmission(Fixture):
    def test_original_cli_creates_signed_pending_proposal_and_fixed_vote(self):
        self.run_core('_internal_governance_propose_engine "OpenCI test" compute/openci:0 '+('b'*64)+' '+('c'*64)+' 1')
        with closing(sqlite3.connect(self.chain)) as db:
            proposal=db.execute("SELECT hash FROM transactions WHERE type='propose_new_compute_engine'").fetchone()[0]
        self.run_core('vote_tx_type=unrelated_action; _internal_governance_vote_engine '+shlex.quote(proposal)+' yes')
        with closing(sqlite3.connect(self.chain)) as db:
            rows=db.execute("SELECT type,data,timestamp,signature,block_height FROM transactions WHERE type IN ('propose_new_compute_engine','vote_on_compute_engine') ORDER BY type").fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(db.execute('SELECT count(*) FROM compute_engines').fetchone()[0],0)
        for kind,data,timestamp,signature,height in rows:
            self.assertIsNone(height)  # Local signed admission is not consensus approval.
            canonical='{"type":'+json.dumps(kind)+',"data":'+data+',"timestamp":'+str(timestamp)+'}'
            self.key.public_key().verify(bytes.fromhex(signature),canonical.encode(),ec.ECDSA(hashes.SHA256()))
        vote=next(json.loads(row[1]) for row in rows if row[0]=='vote_on_compute_engine')
        self.assertEqual(vote,{'proposal_tx_hash':proposal,'vote':'yes'})
