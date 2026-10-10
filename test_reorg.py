#!/usr/bin/env python3
"""Exercise real reorganization over TLS using the production gateway and transport."""
import ast,datetime,hashlib,http.server,ipaddress,json,pathlib,sqlite3,ssl,threading,unittest,os,subprocess,signal,time,shlex
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from test_core import Fixture
from test_gateway import SOURCE,DAEMON

class ReorgTests(Fixture):
    def setUp(self):
        super().setUp()
        self.remote=self.root/'peer/chain.db';self.remote.parent.mkdir()
        with sqlite3.connect(self.chain) as src,sqlite3.connect(self.remote) as dst:src.backup(dst)
        os.environ['SCRIPT_PATH']=str(SOURCE)
        namespace={'__name__':'corium_reorg_gateway'};nodes=ast.parse(DAEMON).body
        boundary=next(i for i,n in enumerate(nodes) if isinstance(n,ast.ClassDef) and n.name=='SandboxAPI')
        exec(compile(ast.Module(body=nodes[:boundary],type_ignores=[]),str(SOURCE)+':daemon','exec'),namespace)
        namespace.update(SCRIPT_PATH=str(SOURCE),BLOCKCHAIN_DB_PATH=str(self.remote),FORUM_DB_PATH=str(self.forum),DHT_DB_PATH=str(self.dht),USER_PUBLIC_KEY_FILE=str(self.etc/'identity.key.pub'),OUR_NODE_ID_CACHE=None)
        self.ns=namespace
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),namespace['CoriumGatewayHandler'])
        self.port=server.server_address[1]-1000
        tls_key=ec.generate_private_key(ec.SECP256R1())
        tlsfile=self.root/'peer/tls.key';tlsfile.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,self.identity)]))
              .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,self.identity)]))
              .public_key(tls_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=1))
              .not_valid_after(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
              .sign(tls_key,hashes.SHA256()))
        certfile=self.root/'peer/cert.pem';certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        cache=self.root/'var/lib/corix/p2p/peer_certs';cache.mkdir(parents=True)
        (cache/f'127.0.0.1_{self.port}.pem').write_bytes(certfile.read_bytes())
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(str(certfile),str(tlsfile))
        server.socket=ctx.wrap_socket(server.socket,server_side=True)
        self.thread=threading.Thread(target=server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.run_core(f'dht_add_node {self.identity} tcp 127.0.0.1 {self.port}')
        self.genesis=self.tip(self.chain)
    def tip(self,path):
        with sqlite3.connect(path) as db:return db.execute('SELECT hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()[0]
    def branch(self,path,depth,start_timestamp=10,invalid_height=None,txs=None):
        with sqlite3.connect(path) as db:
            previous=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
            db.execute('DELETE FROM blocks WHERE height>0')
            for height in range(1,depth+1):
                transactions=(txs or {}).get(height,[])
                content=json.dumps({'height':height,'previous_hash':previous,'timestamp':start_timestamp+height,'transactions':transactions},separators=(',',':'))
                digest=hashlib.sha256(content.encode()).hexdigest();signature='00' if height==invalid_height else self.sign(content)
                db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)',(height,digest,previous,start_timestamp+height,self.identity,signature,json.dumps(transactions,separators=(',',':')),height*1000))
                previous=digest
            db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)",(previous+'|'+str(depth),))
        return previous
    def reorganize(self,tip,ok=True):return self.run_core(f'_blockchain_reorganize_to {tip} 127.0.0.1 {self.port}',ok)
    def assert_replay(self):
        current=self.semantic()
        result=self.run_core('replay=$(mktemp -d -p "$BUILD_TMP_DIR_BASE"); _internal_replay_chain_state "$(db_query_static "$BLOCKCHAIN_DB" "SELECT MAX(height) FROM blocks;")" "$replay"; BLOCKCHAIN_DB="$replay/chain.db"; FORUM_DB="$replay/forum.db"; _internal_semantic_state')
        self.assertEqual(current,json.loads(result.stdout.splitlines()[-1]))
    def test_reorg_zero_one_multiple_deep_repeat_and_phoenix(self):
        self.reorganize(self.genesis)
        for index,(local_depth,remote_depth) in enumerate([(1,2),(2,4),(4,8),(8,10)]):
            self.branch(self.chain,local_depth,10+index*30);self.run_core('_internal_rebuild_derived_state')
            tip=self.branch(self.remote,remote_depth,20+index*30)
            self.reorganize(tip);self.assertEqual(self.tip(self.chain),tip);self.assert_replay()
            snapshot=self.snapshot(f'reorg-{index}.json',height=remote_depth)
            self.assertEqual(snapshot['recovery_anchor']['block_hash'],tip)
            self.reorganize(tip);self.assert_replay()
    def test_reorg_equal_weight_invalid_signature_and_failed_halfway_atomic(self):
        self.branch(self.chain,2,10);self.run_core('_internal_rebuild_derived_state');before=self.semantic()
        tip=self.branch(self.remote,2,30);self.reorganize(tip,False);self.assertEqual(self.semantic(),before)
        tip=self.branch(self.remote,4,30,invalid_height=3);self.reorganize(tip,False);self.assertEqual(self.semantic(),before)
        # Restart the actual shell after failure and accept a valid competing branch.
        tip=self.branch(self.remote,4,30);self.reorganize(tip);self.assert_replay()
    def test_reorg_invalid_transaction_duplicate_and_state_transition_replay(self):
        # Existing identity registration updates a real derived table.
        data={'nickname':'中文|🙂'};timestamp=1
        payload=json.dumps({'type':'set_nickname','data':data,'timestamp':timestamp},ensure_ascii=False,separators=(',',':'))
        tx=hashlib.sha256(payload.encode()).hexdigest();signature=self.sign(payload)
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,NULL)',(tx,'set_nickname',json.dumps(data,ensure_ascii=False,separators=(',',':')),signature,self.pem,timestamp))
        tip=self.branch(self.remote,2,10,txs={1:[tx]});self.reorganize(tip);self.assert_replay()
        state=self.semantic();self.assertTrue(any(row['nickname']=='中文|🙂' for row in state['application']['identity_cache']))
        # Repeated transaction in a later block is rejected without modifying that state.
        tip=self.branch(self.remote,4,20,txs={1:[tx],2:[tx]});self.reorganize(tip,False);self.assertEqual(self.semantic(),state)
        with sqlite3.connect(self.chain) as db:db.execute('UPDATE transactions SET signature=? WHERE hash=?',('00',tx))
        before=self.semantic();tip=self.branch(self.remote,4,30,txs={1:[tx]});self.reorganize(tip,False);self.assertEqual(self.semantic(),before)

    def remote_nickname(self,nickname='同步|中文🙂'):
        data={'nickname':nickname};timestamp=1
        payload=json.dumps({'type':'set_nickname','data':data,'timestamp':timestamp},ensure_ascii=False,separators=(',',':'))
        digest=hashlib.sha256(payload.encode()).hexdigest()
        with sqlite3.connect(self.remote) as db:
            db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,NULL)',(digest,'set_nickname',json.dumps(data,ensure_ascii=False,separators=(',',':')),self.sign(payload),self.pem,timestamp))
        return digest
    def sync(self,ok=True,extra=''):
        return self.run_core('mkdir -p "$REPOS_CONF_DIR"; '+extra+' corix_sync <<< y',ok)
    def test_sync_verifies_remote_transaction_full_pem_and_semantic_replay(self):
        tx=self.remote_nickname();tip=self.branch(self.remote,2,20,txs={1:[tx]})
        self.sync();self.assert_replay()
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT hash FROM blocks WHERE height=2').fetchone()[0],tip)
            outgoing=db.execute("SELECT data FROM transactions WHERE type='ibc_dispatch' AND block_height IS NOT NULL").fetchall()
            self.assertEqual(len(outgoing),1);self.assertEqual(json.loads(outgoing[0][0])['message_type'],'IBC_IDENTITY_SYNC')
        with sqlite3.connect(self.chain) as db:
            row=db.execute('SELECT public_key,signature,block_height FROM transactions WHERE hash=?',(tx,)).fetchone()
            self.assertEqual(row[0],self.pem);self.assertEqual(row[2],1);self.assertNotEqual(row[1],self.pem)
        self.sync();self.assert_replay();self.snapshot('after-sync.json',2)
    def test_sync_forged_missing_duplicate_transaction_and_checkpoint_atomic(self):
        before=self.semantic();tx=self.remote_nickname()
        tip=self.branch(self.remote,3,20,invalid_height=2,txs={1:[tx]})
        self.sync(False);self.assertEqual(self.semantic(),before)
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions WHERE hash=?',(tx,)).fetchone()[0],0)
        self.branch(self.remote,3,30,txs={1:[tx],2:[tx]})
        self.sync(False);self.assertEqual(self.semantic(),before)
        self.branch(self.remote,2,40,txs={1:['f'*64]})
        self.sync(False);self.assertEqual(self.semantic(),before)
        self.branch(self.remote,2,50,txs={1:[tx]})
        self.sync(False,'BLOCKCHAIN_WSC="1:00000000";');self.assertEqual(self.semantic(),before)
        self.sync();self.assert_replay()
    def test_sync_equal_weight_competing_chain_preserves_canonical_state(self):
        self.branch(self.chain,2,10);self.run_core('_internal_rebuild_derived_state');before=self.semantic()
        self.branch(self.remote,2,30);self.sync();self.assertEqual(self.semantic(),before)

    def test_p2p_tls_chunk_binary_range_resume_corruption_and_signed_transaction(self):
        import http.client
        content=bytes(range(256))*20+b'\x00tail\n\n'
        digest=hashlib.sha256(content).hexdigest();file=self.root/'peer/binary';file.write_bytes(b'prefix'+content+b'suffix')
        with sqlite3.connect(self.dht) as db:db.execute('INSERT INTO local_chunks VALUES (?,?,?,?)',(digest,str(file),6,len(content)))
        ctx=ssl.create_default_context(cafile=str(self.root/'peer/cert.pem'));ctx.check_hostname=False
        def request(path,headers=None):
            connection=http.client.HTTPSConnection('127.0.0.1',self.port+1000,context=ctx,timeout=10)
            try:
                connection.request('GET',path,headers=headers or {});response=connection.getresponse()
                return response.status,response.read(),dict(response.getheaders())
            finally:connection.close()
        status,data,headers=request('/chunk/'+digest);self.assertEqual(status,200);self.assertEqual(data,content)
        for spec,expected in [('bytes=13-',content[13:]),('bytes=1-4',content[1:5]),('bytes=-3',content[-3:])]:
            status,data,headers=request('/chunk/'+digest,{'Range':spec});self.assertEqual(status,206);self.assertEqual(data,expected)
        for value in ('bytes=999999-','bytes=1-0','bytes=-0','bytes=0-1,3-4','nonsense'):
            self.assertEqual(request('/chunk/'+digest,{'Range':value})[0],416)
        self.assertEqual(request('/chunk/invalid')[0],400)
        self.assertEqual(request('/chunk/'+('f'*64))[0],404)
        file_port=self.port-1000
        cache=self.root/'var/lib/corix/p2p/peer_certs'/f'127.0.0.1_{file_port}.pem';cache.write_bytes((self.root/'peer/cert.pem').read_bytes())
        destination=self.root/'download.bin';destination.write_bytes(content[:13])
        self.run_core(f'p2p_request_chunk 127.0.0.1 {file_port} {digest} "$CORIUM_ROOT/download.bin"')
        self.assertEqual(destination.read_bytes(),content)
        # The established transaction ID hashes the signed body, not the envelope bytes.
        result=self.run_core('blockchain_create_transaction set_nickname '+shlex.quote(json.dumps({'nickname':'签名🙂'},ensure_ascii=False)))
        tx=result.stdout.splitlines()[-1];self.assertEqual(request('/chunk/'+tx)[0],200)
        self.run_core('_p2p_download_object '+tx+' "$CORIUM_ROOT/transaction.json"')
        self.assertEqual(json.loads((self.root/'transaction.json').read_text())['data']['nickname'],'签名🙂')
        file.write_bytes(b'prefix'+b'corrupt'.ljust(len(content),b'x')+b'suffix')
        self.assertEqual(request('/chunk/'+digest)[0],500)
        self.run_core('_p2p_download_object '+digest+' "$CORIUM_ROOT/download.bin"',False)
        self.assertEqual(destination.read_bytes(),content)

    def test_authenticated_block_announcement_applies_real_remote_branch_and_deduplicates(self):
        # Execute the unchanged receiver declarations with this node's real database paths.
        os.environ.update(SCRIPT_PATH=str(SOURCE),CORIUM_ROOT=str(self.root),CORIUM_NETWORK_ID_OVERRIDE='default')
        namespace={'__name__':'corium_receiver'};nodes=ast.parse(DAEMON).body
        boundary=next(i for i,n in enumerate(nodes) if isinstance(n,ast.ClassDef) and n.name=='SandboxAPI')
        exec(compile(ast.Module(body=nodes[:boundary],type_ignores=[]),str(SOURCE)+':receiver','exec'),namespace)
        namespace.update(SCRIPT_PATH=str(SOURCE),BLOCKCHAIN_DB_PATH=str(self.chain),FORUM_DB_PATH=str(self.forum),DHT_DB_PATH=str(self.dht),USER_PUBLIC_KEY_FILE=str(self.etc/'identity.key.pub'),OUR_NODE_ID_CACHE=None)
        receiver=namespace['CoriumGatewayHandler'].__new__(namespace['CoriumGatewayHandler'])
        tip=self.branch(self.remote,2,30)
        payload='|'.join([tip,'2','127.0.0.1',str(self.port),self.identity,self.sign(tip+'|2')])
        def announce(body):
            return receiver.handle_dht_message({'type':'ANNOUNCE_BLOCK','payload':body,'sender_id':self.identity,'signature':self.sign('ANNOUNCE_BLOCK|'+body)})
        self.assertEqual(announce(payload),{'status':'success','data':'BLOCK_ACCEPTED'})
        self.assertEqual(self.tip(self.chain),tip);self.assert_replay();before=self.semantic()
        self.assertEqual(announce(payload),{'status':'success','data':'BLOCK_KNOWN'})
        for body in (payload.rsplit('|',1)[0]+'|00',payload+'|extra',payload.replace('|2|','|3|'),payload.replace(self.identity,'0'*64)):
            self.assertEqual(announce(body)['status'],'error');self.assertEqual(self.semantic(),before)

    def test_interrupted_reorg_term_rolls_back_and_restart(self):
        self.branch(self.chain,2,10);self.run_core('_internal_rebuild_derived_state');before=self.semantic()
        tip=self.branch(self.remote,8,100)
        script='source '+shlex.quote(str(SOURCE))+f'\n_blockchain_reorganize_to {tip} 127.0.0.1 {self.port}'
        output=self.root/'interrupted.log'
        with output.open('w') as log:
            proc=subprocess.Popen(['bash','-c',script],env=self.env,stdout=log,stderr=log,start_new_session=True)
            try:
                deadline=time.monotonic()+60;observed=False
                while time.monotonic()<deadline and proc.poll() is None:
                    with sqlite3.connect(self.chain) as db:
                        row=db.execute('SELECT timestamp FROM blocks WHERE height=1').fetchone()
                    if row and row[0]==101:
                        observed=True;os.killpg(proc.pid,signal.SIGTERM);break
                    time.sleep(0.025)
                self.assertTrue(observed,'Did not reach partial alternate apply: '+output.read_text())
                self.assertNotEqual(proc.wait(timeout=30),0)
            finally:
                if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        self.assertEqual(self.semantic(),before,'Interrupted reorg changed semantic state: '+output.read_text())
        self.reorganize(tip);self.assert_replay();self.snapshot('after-interrupt.json',8)

if __name__=='__main__':unittest.main(verbosity=2)
