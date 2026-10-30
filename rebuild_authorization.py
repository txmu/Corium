"""Read-only verification of an explicit, signed mainnet rebuild permission.

This admission permission never validates transactions or replaces native block
validation. It binds an operator-approved branch anchor, database and source.
"""
import hashlib,json,os,re,sqlite3,stat,time
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import ec

SCHEMA='ziokt.native-rebuild-authorization.v1'
DOMAIN=b'Ziokt/native-rebuild-authorization/v1\n'
FIELDS={'schema','network_id','genesis_hash','anchor_height','anchor_hash','canonical_database_path','native_source_sha256','authorized_max_height','expires_at','validator','validator_pubkey','signature'}

def signing_bytes(value):return DOMAIN+json.dumps({k:v for k,v in value.items() if k!='signature'},sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def verify(value):
 try:
  if not isinstance(value,dict) or set(value)!=FIELDS or value['schema']!=SCHEMA or value['network_id']!='ziokt-main':return False
  if any(type(value[k])is not int for k in ['anchor_height','authorized_max_height','expires_at']):return False
  if not 0<=value['anchor_height']<=value['authorized_max_height']<=2**32-1 or not int(time.time())<value['expires_at']<=int(time.time())+366*86400:return False
  if any(not isinstance(value[k],str) or not re.fullmatch('[a-f0-9]{64}',value[k]) for k in ['genesis_hash','anchor_hash','native_source_sha256','validator']):return False
  root=Path(os.environ['CORIUM_ROOT']).resolve();expected=root/'var/lib/corix/networks/ziokt-main/blockchain/chain.db';path=Path(value['canonical_database_path'])
  if not path.is_absolute() or path.is_symlink() or path.resolve()!=expected:return False
  if os.environ.get('CORIUM_NETWORK_ID_OVERRIDE')!='ziokt-main':return False
  source=Path(os.environ.get('CORIUM_REBUILD_NATIVE_SOURCE',str(Path(__file__).with_name('corix_v108.sh'))))
  if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=value['native_source_sha256']:return False
  genesis=json.loads((root/'etc/corix/networks/ziokt-main/genesis.json').read_text());public=value['validator_pubkey'].rstrip('\n')
  if not any(v.get('public_key','').rstrip('\n')==public for v in genesis['genesis_validators']):return False
  if hashlib.sha256(public.encode()).hexdigest()!=value['validator']:return False
  key=serialization.load_pem_public_key(public.encode())
  if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256K1):return False
  key.verify(bytes.fromhex(value['signature']),signing_bytes(value),ec.ECDSA(hashes.SHA256()))
  with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
   first=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone();anchor=db.execute('SELECT hash FROM blocks WHERE height=?',(value['anchor_height'],)).fetchone();tip=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
   if not first or first[0]!=value['genesis_hash'] or not anchor or anchor[0]!=value['anchor_hash'] or not value['anchor_height']<=tip<value['authorized_max_height']:return False
   rows=db.execute('SELECT height,hash,previous_hash FROM blocks WHERE height>=? ORDER BY height',(value['anchor_height'],)).fetchall()
   if len(rows)!=tip-value['anchor_height']+1:return False
   for a,b in zip(rows,rows[1:]):
    if b[0]!=a[0]+1 or b[2]!=a[1]:return False
  return True
 except Exception:return False
