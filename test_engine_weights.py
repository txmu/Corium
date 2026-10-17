"""Exercise native scheduled PoUW activation against real SQLite and Bash helpers."""
import json,os,sqlite3,subprocess,tempfile,unittest
from pathlib import Path
from test_gateway import schema,SOURCE

class EngineWeightTests(unittest.TestCase):
 def test_native_scheduled_activation_preserves_weight(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);db=root/'chain.db';engine='e'*64
   with sqlite3.connect(db) as con:
    con.executescript(schema('_init_blockchain_db'))
    con.execute('INSERT INTO compute_engines(engine_id,pkg_id,description,compute_program_hash,verifier_script_hash,is_active,reward_weight) VALUES(?,?,?,?,?,0,100)',(engine,'compute/test:0','test','a'*64,'b'*64))
    con.execute('INSERT INTO scheduled_state_changes(proposal_hash,enactment_height,type,data) VALUES(?,42,?,?)',(engine,'propose_new_compute_engine',json.dumps({'reward_weight':7})))
   env={**os.environ,'CORIUM_ROOT':str(root/'state'),'TEST_DATABASE':str(db),'TEST_TMP':directory,'CORIX_SOURCE':str(SOURCE)}
   result=subprocess.run(['bash','-c','source "$CORIX_SOURCE"; BLOCKCHAIN_DB="$TEST_DATABASE"; BUILD_TMP_DIR_BASE="$TEST_TMP"; _protocol_execute_scheduled_changes 42'],env=env,capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,0,result.stderr)
   with sqlite3.connect(db) as con:
    self.assertEqual(con.execute('SELECT is_active,reward_weight FROM compute_engines WHERE engine_id=?',(engine,)).fetchone(),(1,7))
    self.assertEqual(con.execute('SELECT count(*) FROM scheduled_state_changes').fetchone()[0],0)
