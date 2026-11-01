"""A real stalled TCP/TLS peer must not inherit a block replay's 610s budget."""
import datetime,socket,sqlite3,threading,time
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.x509.oid import NameOID
from test_core import Fixture

class PeerDeadlineTests(Fixture):
 core_timeout=8
 def test_block_announcement_bounds_connect_and_tls_handshake(self):
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);self.addCleanup(listener.close)
  stop=threading.Event();self.addCleanup(stop.set)
  def stall():
   peer,_=listener.accept()
   with peer:stop.wait(5)
  thread=threading.Thread(target=stall,daemon=True);thread.start()
  port=listener.getsockname()[1]-1000;peer_id='c'*64
  with sqlite3.connect(self.dht)as db:db.execute('INSERT INTO nodes(id,address_type,address,port,capabilities,last_seen,distance) VALUES(?,?,?,?,?,?,?)',(peer_id,'ipv4','127.0.0.1',port,'{}',int(time.time()),'0'))
  now=datetime.datetime.now(datetime.timezone.utc);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'deadline-test')])
  cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(self.key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).sign(self.key,hashes.SHA256())
  from pathlib import Path
  cache=Path(self.run_core('printf "%s" "$PEER_CERT_CACHE"').stdout);cache.mkdir(parents=True,exist_ok=True)
  (cache/('127.0.0.1_'+str(port)+'.pem')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
  started=time.monotonic();result=self.run_core('P2P_MESSAGE_TIMEOUT=1; _dht_send_message_direct '+peer_id+' ANNOUNCE_BLOCK deadline-regression',False)
  self.assertEqual(result.returncode,2);self.assertLess(time.monotonic()-started,4)
  stop.set();thread.join(2)
