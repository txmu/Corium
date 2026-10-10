"""Run the unmodified production gateway over TLS as a real independent peer."""
import argparse
import ast
import datetime
import http.server
import json
import os
import pathlib
import signal
import ssl
import threading
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from test_core import Fixture
from test_gateway import SOURCE,DAEMON

parser=argparse.ArgumentParser(); parser.add_argument('--ready',required=True); parser.add_argument('--host',default='0.0.0.0'); parser.add_argument('--port',type=int,default=19345)
args=parser.parse_args()
fixture=Fixture(); fixture.setUp()
os.environ.update(fixture.env,SCRIPT_PATH=str(SOURCE),CORIUM_NETWORK_ID='default')
namespace={'__name__':'corium_native_peer'}; nodes=ast.parse(DAEMON).body
boundary=next(i for i,n in enumerate(nodes) if isinstance(n,ast.ClassDef) and n.name=='SandboxAPI')
exec(compile(ast.Module(body=nodes[:boundary],type_ignores=[]),str(SOURCE)+':daemon','exec'),namespace)
namespace.update(SCRIPT_PATH=str(SOURCE),BLOCKCHAIN_DB_PATH=str(fixture.chain),FORUM_DB_PATH=str(fixture.forum),DHT_DB_PATH=str(fixture.dht),USER_PUBLIC_KEY_FILE=str(fixture.etc/'identity.key.pub'),OUR_NODE_ID_CACHE=None)
key=ec.generate_private_key(ec.SECP256R1())
subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,fixture.identity)])
cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=5)).not_valid_after(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1))
      .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
certpath=fixture.root/'peer.pem'; certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
keypath=fixture.root/'tls.key'; keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
server=http.server.ThreadingHTTPServer((args.host,args.port),namespace['CoriumGatewayHandler'])
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(certpath,keypath); server.socket=context.wrap_socket(server.socket,server_side=True)
thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
pathlib.Path(args.ready).write_text(json.dumps({'root':str(fixture.root),'id':fixture.identity,'cert':str(certpath),'port':args.port-1000,'dht':str(fixture.dht),'chain':str(fixture.chain),'pem':fixture.pem}))
stop=threading.Event()
for signum in (signal.SIGTERM,signal.SIGINT): signal.signal(signum,lambda *_:stop.set())
try: stop.wait()
finally: server.shutdown(); server.server_close(); fixture.doCleanups()
