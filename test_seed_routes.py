"""Prevent synthetic bootstrap handles from becoming persistent advertised peers."""
import hashlib,json,os,sqlite3,subprocess,time,unittest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
import test_gateway as fixtures

class SeedRouteTests(unittest.TestCase):
 def setUp(self):
  fixtures.GatewayTests.setUp(self);self.alias=hashlib.sha256(b'ipv4:13.112.54.178:7234').hexdigest();self.real='b'*64
 def insert(self,identity,address='13.112.54.178',port=7234,capabilities='{}',seen=None):
  with sqlite3.connect(self.dht)as db:db.execute('INSERT INTO nodes(id,address_type,address,port,capabilities,last_seen,distance) VALUES(?,?,?,?,?,?,?)',(identity,'ipv4',address,port,capabilities,int(time.time())if seen is None else seen,'0'))
 def core(self,operation):
  return subprocess.run(['bash','-c','source "$1"; DHT_DB="$2"; '+operation,'seed-routes',str(fixtures.SOURCE),str(self.dht)],capture_output=True,text=True,timeout=15)
 def test_old_alias_is_pruned_but_authenticated_identity_at_new_port_remains(self):
  self.insert(self.alias);self.insert(self.real,port=33434)
  result=self.core('_corium_prune_seed_placeholders');self.assertEqual(result.returncode,0,result.stderr)
  with sqlite3.connect(self.dht)as db:self.assertEqual(db.execute('SELECT id,port FROM nodes').fetchall(),[(self.real,33434)])
 def test_native_discovery_never_advertises_an_alias_or_provider_alias(self):
  self.insert(self.alias);self.insert(self.real,port=33434);chunk='a'*64
  with sqlite3.connect(self.dht)as db:db.execute('INSERT INTO chunks(hash,nodes,last_updated) VALUES(?,?,?)',(chunk,json.dumps([self.alias]),int(time.time())))
  for kind in ['FIND_NODE','FIND_VALUE']:
   message=kind+'|'+chunk;packet={'type':kind,'payload':chunk,'sender_id':self.identity,'public_key':self.pem,'signature':self.key.sign(message.encode(),ec.ECDSA(hashes.SHA256())).hex()}
   response=self.handler.handle_dht_message(packet);self.assertEqual(response['status'],'success');self.assertNotIn(self.alias,response['data']);self.assertIn(self.real,response['data'])
 def test_only_local_short_lived_bootstrap_can_insert_a_placeholder(self):
  command='dht_add_node '+self.alias+' ipv4 13.112.54.178 7234'
  result=self.core(command);self.assertNotEqual(result.returncode,0)
  result=self.core('CORIUM_BOOTSTRAP_PENDING=1 '+command+' \'{"bootstrap_pending":true}\'');self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(self.core('_corium_prune_seed_placeholders').returncode,0)
  with sqlite3.connect(self.dht)as db:
   self.assertEqual(db.execute('SELECT id FROM nodes').fetchone(),(self.alias,));db.execute('UPDATE nodes SET last_seen=?',(int(time.time())-121,))
  self.assertEqual(self.core('_corium_prune_seed_placeholders').returncode,0)
  with sqlite3.connect(self.dht)as db:self.assertIsNone(db.execute('SELECT id FROM nodes').fetchone())
