"""Execute the production embedded browser-signature recovery verifier."""
import hashlib,json,pathlib,secrets,subprocess,sys,tempfile,time,unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

class BrowserForumTests(unittest.TestCase):
 def test_recovery_signature_kind_network_and_content_binding(self):
  source=pathlib.Path(__file__).with_name('corix_v108.sh').read_text()
  verifier=source.split("<<'PY_FORUM_V3'\n",1)[1].split('\nPY_FORUM_V3',1)[0]
  key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes_raw().hex()
  unsigned={'schema':'ziokt.forum.v3','network':'test','title':'Browser author','content':'Signed 世界','reply_to':'','timestamp':int(time.time()),'nonce':secrets.token_hex(32),'public_key':public}
  signature=key.sign(json.dumps(unsigned,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hex()
  manifest={**unsigned,'signature':signature,'version':'3.0','author':hashlib.sha256(bytes.fromhex(public)).hexdigest(),'content_hash':hashlib.sha256(unsigned['content'].encode()).hexdigest(),'attachment_hash':'','attachment_name':'','associated_group_id':None}
  with tempfile.TemporaryDirectory() as directory:
   path=pathlib.Path(directory)/'manifest';script=pathlib.Path(directory)/'verify.py';script.write_text(verifier)
   def check(value,network='test',kind='topic'):
    path.write_text(json.dumps(value));return subprocess.run([sys.executable,str(script),str(path),network,kind],capture_output=True).returncode
   self.assertEqual(check(manifest),0)
   for changes in [{'content':'forged'},{'author':'0'*64},{'signature':'00'},{'title':'changed'},{'attachment_hash':'a'*64}]:self.assertNotEqual(check({**manifest,**changes}),0)
   self.assertNotEqual(check(manifest,'other'),0);self.assertNotEqual(check(manifest,kind='post'),0)
