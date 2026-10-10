"""Real RSA OpenPGP fixture packets, verified by production GnuPG. No agent required."""
import struct,time,hashlib
from cryptography.hazmat.primitives.asymmetric import rsa,padding,utils
from cryptography.hazmat.primitives import hashes
class OpenPGPFixture:
 def __init__(self):
  self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048);self.now=int(time.time());n=self.key.public_key().public_numbers()
  self.public=b'\4'+struct.pack('>I',self.now)+b'\1'+self.mpi(n.n)+self.mpi(n.e)
  self.fingerprint=hashlib.sha1(b'\x99'+struct.pack('>H',len(self.public))+self.public).digest()
 def mpi(self,n):return struct.pack('>H',n.bit_length())+n.to_bytes((n.bit_length()+7)//8,'big')
 def packet(self,tag,data):return bytes([0xc0|tag,255])+struct.pack('>I',len(data))+data
 def signature(self,data,kind=0):
  sub=b'\x05\x02'+struct.pack('>I',self.now);header=bytes([4,kind,1,8])+struct.pack('>H',len(sub))+sub
  digest=hashlib.sha256(data+header+b'\4\xff'+struct.pack('>I',len(header))).digest()
  signature=self.key.sign(digest,padding.PKCS1v15(),utils.Prehashed(hashes.SHA256()))
  issuer=b'\x09\x10'+self.fingerprint[-8:]
  return self.packet(2,header+struct.pack('>H',len(issuer))+issuer+digest[:2]+self.mpi(int.from_bytes(signature,'big')))
 def keyring(self):
  user=b'Corium regression <test@invalid>'
  signed=b'\x99'+struct.pack('>H',len(self.public))+self.public+b'\xb4'+struct.pack('>I',len(user))+user
  return self.packet(6,self.public)+self.packet(13,user)+self.signature(signed,0x13)

 def armor(self,data,kind):
  import base64,textwrap
  crc=0xb704ce
  for byte in data:
   crc^=byte<<16
   for _ in range(8):
    crc<<=1
    if crc&0x1000000:crc^=0x1864cfb
  checksum=base64.b64encode((crc&0xffffff).to_bytes(3,'big')).decode()
  return '-----BEGIN PGP '+kind+'-----\n\n'+'\n'.join(textwrap.wrap(base64.b64encode(data).decode(),64))+'\n='+checksum+'\n-----END PGP '+kind+'-----\n'
