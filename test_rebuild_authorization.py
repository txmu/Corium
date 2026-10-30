"""Real native genesis/key fixture verifies bounded rebuild admission."""
import copy,hashlib,json,time
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from test_core import Fixture
from test_gateway import SOURCE
import rebuild_authorization as a

class RebuildAuthorizationTests(Fixture):
 def setUp(self):
  self.network_id='ziokt-main';super().setUp();self.path=self.root/'hold.json';self.env['CORIUM_CONSENSUS_HOLD_FILE']=str(self.path)
  self.auth={'schema':a.SCHEMA,'network_id':'ziokt-main','genesis_hash':self.run_core('blockchain_get_latest_hash').stdout.strip().splitlines()[-1],'anchor_height':0,'anchor_hash':self.run_core('blockchain_get_latest_hash').stdout.strip().splitlines()[-1],'canonical_database_path':str(self.chain),'native_source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'authorized_max_height':2,'expires_at':int(time.time())+3600,'validator':self.identity,'validator_pubkey':self.pem}
 def write(self,changes=None):
  value=dict(self.auth,**(changes or {}));value['signature']=self.key.sign(a.signing_bytes(value),ec.ECDSA(hashes.SHA256())).hex();self.path.write_text(json.dumps({'schema':'ziokt.consensus-safety-hold.v1','active':False,'authorized_recovery':value}));self.path.chmod(0o600)
 def test_native_admission_and_wrong_path_expiry_source_denied(self):
  self.write();self.run_core('_internal_consensus_safety_check')
  for changes in [{'canonical_database_path':str(self.root/'other.db')},{'expires_at':int(time.time())-1},{'native_source_sha256':'f'*64},{'anchor_hash':'0'*64}]:
   self.write(changes);self.run_core('_internal_consensus_safety_check',False)
