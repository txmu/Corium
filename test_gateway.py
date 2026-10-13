#!/usr/bin/env python3
"""Execute the real inlined gateway with real ECDSA, SQLite and Bash IPC.
No replacement handler, database or signature verifier is used.
"""
import ast, hashlib, http.server, json, os, pathlib, re, sqlite3, subprocess, tempfile, threading, time, unittest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

SOURCE = pathlib.Path(os.environ.get('CORIX_BIN', pathlib.Path(__file__).with_name('corix_v108.sh'))).resolve()
TEXT = SOURCE.read_text()
DAEMON = TEXT.split("${PYTHON_CMD} - <<'EOF' &\n", 1)[1].split('\nEOF\n', 1)[0]

def schema(name):
    body = TEXT.split(name + '() {', 1)[1].split('\n}\n', 1)[0]
    sql = re.search(r'db_init "\$[A-Z_]+" "(.*?)\n    "', body, re.S).group(1)
    return re.sub(r'^\s*#', '--', sql, flags=re.M).replace('\\"', '"')

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='corium-gateway.')
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.chain = self.root/'var/lib/corix/networks/default/blockchain/chain.db'
        self.forum = self.root/'var/lib/corix/networks/default/forum/forum.db'
        self.dht = self.root/'var/lib/corix/p2p/dht.db'
        for path, name in [(self.chain, '_init_blockchain_db'), (self.forum, '_init_app_db'), (self.dht, '_init_dht_db')]:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as db: db.executescript(schema(name))
        self.key = ec.generate_private_key(ec.SECP256K1())
        self.pem = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
        self.identity = hashlib.sha256(self.pem.encode()).hexdigest()
        self.pubfile = self.root/'etc/corix/networks/default/identity.key.pub'; self.pubfile.parent.mkdir(parents=True); self.pubfile.write_text(self.pem+'\n')
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO validators (public_key,public_key_hash,stake) VALUES (?,?,?)',(self.pem,self.identity,1000))
        os.environ.update(CORIUM_ROOT=str(self.root), CORIUM_NETWORK_ID='default', CORIUM_NETWORK_ID_OVERRIDE='default')
        os.environ['SCRIPT_PATH']=str(SOURCE)
        namespace = {'__name__': 'corium_gateway_tests'}
        nodes = ast.parse(DAEMON).body
        # Execute the original declarations; leave only the standalone daemon launch unexecuted.
        boundary = next(i for i,n in enumerate(nodes) if isinstance(n,ast.ClassDef) and n.name=='SandboxAPI')
        exec(compile(ast.Module(body=nodes[:boundary],type_ignores=[]), str(SOURCE)+':daemon', 'exec'),namespace)
        namespace.update(SCRIPT_PATH=str(SOURCE), BLOCKCHAIN_DB_PATH=str(self.chain), FORUM_DB_PATH=str(self.forum), DHT_DB_PATH=str(self.dht), USER_PUBLIC_KEY_FILE=str(self.pubfile), OUR_NODE_ID_CACHE=None)
        self.ns = namespace
        self.handler = namespace['CoriumGatewayHandler'].__new__(namespace['CoriumGatewayHandler'])

    def sign(self, value): return self.key.sign(value.encode(), ec.ECDSA(hashes.SHA256())).hex()
    def rpc(self, kind, payload, envelope_key=None):
        body = payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=True)
        key = envelope_key or self.key
        envelope = {'type':kind,'payload':body,'sender_id':self.identity,'signature':key.sign((kind+'|'+body).encode(),ec.ECDSA(hashes.SHA256())).hex()}
        return self.handler.handle_dht_message(envelope)
    def cbb(self, message='中文🙂|\nquote"\\', ts=None):
        ts = int(time.time()) if ts is None else ts
        body = {'author_id':self.identity,'timestamp':ts,'message':message}
        body['signature']=self.sign(f'CORIUM-CBB-V1\ndefault\n{self.identity}\n{ts}\n{message}')
        return body
    def count(self, table):
        with sqlite3.connect(self.forum) as db:return db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def proposal(self):
        ts=int(time.time()); target='a'*64
        with sqlite3.connect(self.chain) as db:
            db.execute("INSERT INTO blocks VALUES (0,?,'0',0,'genesis_node','bootstrap','[]',0)",(target,))
        data={'author_id':self.identity,'target_block_height':0,'target_block_hash':target,'timestamp':ts}
        canonical=f'CORIUM-EXODUS-SSPO-V1\ndefault\n{self.identity}\n0\n{target}\n{ts}'
        data['signature']=self.sign(canonical)
        return data,hashlib.sha256(canonical.encode()).hexdigest()

    def test_cbb_real_ipc_unicode_dedup_sync(self):
        data=self.cbb()
        for _ in range(3): self.assertEqual(self.rpc('CBB_POST',data)['status'],'success')
        self.assertEqual(self.count('cbb_messages'),1)
        messages=json.loads(self.rpc('CBB_SYNC_REQUEST','')['data'])
        self.assertEqual(messages[0]['message'],data['message'])
    def test_cbb_forged_and_malformed_no_write(self):
        for change in [{'author_id':'0'*64},{'signature':'00'},{'message':'modified'},{'timestamp':True},{'timestamp':-1},{'timestamp':int(time.time())+301},{'message':'x'*65537},{'message':'\x00'},{'message':'\ud800'}]:
            data=self.cbb(); data.update(change)
            with self.subTest(change=repr(change)[:70]): self.assertEqual(self.rpc('CBB_POST',data)['status'],'error')
        self.assertEqual(self.count('cbb_messages'),0)
    def test_cbb_stale_and_cross_network(self):
        self.assertEqual(self.rpc('CBB_POST',self.cbb(ts=int(time.time())-86401))['status'],'error')
        data=self.cbb(); data['signature']=self.sign(f"CORIUM-CBB-V1\nother\n{self.identity}\n{data['timestamp']}\n{data['message']}")
        self.assertEqual(self.rpc('CBB_POST',data)['status'],'error')
        self.assertEqual(self.count('cbb_messages'),0)
    def test_wrong_envelope_key(self):
        wrong=ec.generate_private_key(ec.SECP256K1())
        self.assertEqual(self.rpc('CBB_POST',self.cbb(),wrong)['status'],'error')
        self.assertEqual(self.count('cbb_messages'),0)
    def test_sspo_snso_signed_flow(self):
        data,ph=self.proposal()
        for _ in range(2): self.assertEqual(self.rpc('ANNOUNCE_SSPO',data)['status'],'success')
        notar={'proposal_hash':ph,'notary_id':self.identity,'signature':self.sign(f'CORIUM-EXODUS-SNSO-V1\ndefault\n{ph}\n{self.identity}')}
        for _ in range(2): self.assertEqual(self.rpc('ANNOUNCE_SNSO',notar)['status'],'success')
        self.assertEqual(self.count('exodus_proposals'),1); self.assertEqual(self.count('exodus_notarizations'),1)
        self.assertEqual(len(json.loads(self.rpc('GET_NOTARIZATIONS',ph)['data'])),1)
    def test_sspo_mutations(self):
        data,ph=self.proposal()
        for change in [{'target_block_height':True},{'target_block_hash':'b'*64},{'timestamp':int(time.time())-604801},{'signature':'00'},{'author_id':'0'*64},{'target_block_height':2**63}]:
            candidate={**data,**change}; self.assertEqual(self.rpc('ANNOUNCE_SSPO',candidate)['status'],'error')
        self.assertEqual(self.count('exodus_proposals'),0)
    def test_snso_binding_and_expiry(self):
        data,ph=self.proposal();self.assertEqual(self.rpc('ANNOUNCE_SSPO',data)['status'],'success')
        notar={'proposal_hash':ph,'notary_id':self.identity,'signature':self.sign(f'CORIUM-EXODUS-SNSO-V1\ndefault\n{ph}\n{self.identity}')}
        for change in [{'proposal_hash':'b'*64},{'notary_id':'0'*64},{'signature':'00'}]:self.assertEqual(self.rpc('ANNOUNCE_SNSO',{**notar,**change})['status'],'error')
        with sqlite3.connect(self.forum) as db:db.execute('UPDATE exodus_proposals SET expires_at=0')
        self.assertEqual(self.rpc('ANNOUNCE_SNSO',notar)['status'],'error')
        self.assertEqual(self.count('exodus_notarizations'),0)
    def test_get_full_block_real_schema(self):
        data,ph=self.proposal()
        result=self.rpc('GET_FULL_BLOCK',data['target_block_hash'])
        self.assertEqual(result['status'],'success'); self.assertTrue(result['data'].startswith('BLOCK:'))
        self.assertEqual(json.loads(result['data'][6:])['height'],0)
    def test_invalid_grievance_does_not_consume_token(self):
        with sqlite3.connect(self.dht) as db: db.execute('INSERT INTO distrusted_peers VALUES (?,?,0,0)',(self.identity,self.identity))
        wrong=ec.generate_private_key(ec.SECP256K1())
        self.assertEqual(self.rpc('GRIEVANCE_MESSAGE','forged',wrong)['status'],'error')
        with sqlite3.connect(self.dht) as db:self.assertEqual(db.execute('SELECT grievance_token_used FROM distrusted_peers').fetchone()[0],0)
    def test_db_corruption_is_rejected(self):
        self.forum.write_bytes(b'not sqlite')
        self.assertEqual(self.rpc('CBB_POST',self.cbb())['status'],'error')
    def test_malformed_packets(self):
        for data in [None,[],{}, {'type':'PING','sender_id':'x','payload':'','signature':'aa'}]:self.assertEqual(self.handler.handle_dht_message(data)['status'],'error')
    def test_missing_block(self):self.assertEqual(self.rpc('GET_FULL_BLOCK','b'*64)['status'],'error')

    def test_cached_cbb_corruption_and_database_failure_not_success(self):
        data=self.cbb();self.assertEqual(self.rpc('CBB_POST',data)['status'],'success')
        with sqlite3.connect(self.forum) as db:db.execute('UPDATE cbb_messages SET signature=\'00\'')
        self.assertEqual(self.rpc('CBB_SYNC_REQUEST','')['status'],'error')
        self.forum.write_bytes(b'corrupted')
        self.assertEqual(self.rpc('CBB_SYNC_REQUEST','')['status'],'error')
    def test_duplicate_json_fields_rejected(self):
        data=self.cbb();encoded=json.dumps(data)
        encoded=encoded[:-1]+',"message":"other"}'
        self.assertEqual(self.rpc('CBB_POST',encoded)['status'],'error');self.assertEqual(self.count('cbb_messages'),0)
    def test_sender_supplied_key_bootstrap_and_wrong_binding(self):
        other=ec.generate_private_key(ec.SECP256K1())
        public=other.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
        identity=hashlib.sha256(public.encode()).hexdigest()
        envelope={'type':'PING','payload':'','sender_id':identity,'public_key':public,'signature':other.sign(b'PING|',ec.ECDSA(hashes.SHA256())).hex()}
        self.assertEqual(self.handler.handle_dht_message(envelope)['status'],'success')
        envelope['sender_id']=self.identity
        self.assertEqual(self.handler.handle_dht_message(envelope)['status'],'error')
    def test_find_node_xor_order_and_invalid_target(self):
        for number in [255,1,16]:
            with sqlite3.connect(self.dht) as db:
                db.execute('INSERT INTO nodes(id,address_type,address,port,last_seen,distance) VALUES (?,\'ipv4\',\'127.0.0.1\',?,0,0)',(f'{number:064x}',19000+number))
        response=self.rpc('FIND_NODE','0'*64);self.assertEqual(response['status'],'success')
        ids=[entry.split(':')[0] for entry in response['data'].removeprefix('NODES:').split()]
        self.assertEqual(ids,[f'{n:064x}' for n in [1,16,255]])
        self.assertEqual(self.rpc('FIND_NODE','bad')['status'],'error')

    def test_punch_identity_address_and_worker_admission(self):
        from unittest.mock import patch
        old = os.environ.get('CORIUM_ENABLE_HOLE_PUNCHING')
        os.environ['CORIUM_ENABLE_HOLE_PUNCHING']='true'
        def restore():
            if old is None: os.environ.pop('CORIUM_ENABLE_HOLE_PUNCHING',None)
            else: os.environ['CORIUM_ENABLE_HOLE_PUNCHING']=old
        self.addCleanup(restore)
        target = 'b'*64
        with sqlite3.connect(self.dht) as db:
            for index, identity in enumerate((self.identity,target)):
                db.execute('INSERT INTO nodes(id,address_type,address,port,last_seen,distance) VALUES (?,\'ipv4\',\'127.0.0.1\',?,0,0)',(identity,19000+index))
        with patch.object(self.handler,'_ipc_call',return_value='ok') as ipc:
            for payload in [target+'|'+target+'|ipv4:127.0.0.1',target+'|'+self.identity+'|ipv4:192.0.2.9',target+'|'+self.identity+'|'+'ipv4:127.0.0.1|'*10]:
                self.assertEqual(self.rpc('PUNCH_HOLE_SIGNAL',payload)['status'],'error')
            packet = target+'|'+self.identity+'|ipv4:127.0.0.1'
            self.assertEqual(self.rpc('PUNCH_HOLE_SIGNAL',packet)['status'],'success')
            self.assertIn(self.identity+':ipv4:127.0.0.1:19000',ipc.call_args.args[0][-1])
            self.assertEqual(self.rpc('PUNCH_HOLE_SIGNAL',packet)['status'],'error')
            self.assertEqual(ipc.call_count,1)
    def test_grievance_duplicate_atomic_token_consumption(self):
        with sqlite3.connect(self.dht) as db:db.execute('INSERT INTO distrusted_peers VALUES (?,?,0,0)',(self.identity,self.identity))
        first=self.rpc('GRIEVANCE_MESSAGE','中文🙂')
        self.assertEqual(first['status'],'success')
        self.assertEqual(self.rpc('GRIEVANCE_MESSAGE','中文🙂')['status'],'error')
        self.assertEqual(self.count('messages'),1)
        with sqlite3.connect(self.dht) as db:self.assertEqual(db.execute('SELECT grievance_token_used FROM distrusted_peers').fetchone()[0],1)
    def test_emergency_task_signature_payload_and_target_binding(self):
        agent='a'*64
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO onchain_identities VALUES (?,?,?,?,0)',(agent,self.identity,'mods/test:0',self.pem))
        data={'type':'AGENT_EMERGENCY_TASK','target_agent_id':agent,'task_payload':{'message':'中文🙂'},'proposer_id':self.identity}
        data['signature']=self.sign(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')))
        self.assertEqual(self.rpc('AGENT_EMERGENCY_TASK',data)['status'],'success')
        self.assertEqual(self.rpc('AGENT_EMERGENCY_TASK',data)['status'],'success')
        for change in [{'target_agent_id':'b'*64},{'proposer_id':'b'*64},{'task_payload':{'message':'forged'}},{'signature':'00'}]:
            self.assertEqual(self.rpc('AGENT_EMERGENCY_TASK',{**data,**change})['status'],'error')
        self.assertEqual(self.count('agent_emergency_queue'),1)
    def test_pouw_invalid_proof_does_not_spend_rate_slot(self):
        now=int(time.time())
        for change in [{'node_id':'a'*64},{'start_timestamp':True},{'end_timestamp':now+301},{'signature':'00'}]:
            data={'node_id':self.identity,'start_timestamp':now-60,'end_timestamp':now,'signature':self.sign(f'{self.identity}|{now-60}|{now}')};data.update(change)
            self.assertEqual(self.rpc('/pouw/validate-request',data)['status'],'error')
        with sqlite3.connect(self.dht) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM pouw_rate_limit_log').fetchone()[0],0)

    def test_cached_notarization_corruption_and_db_failure_rejected(self):
        proposal,ph=self.proposal();self.assertEqual(self.rpc('ANNOUNCE_SSPO',proposal)['status'],'success')
        notar={'proposal_hash':ph,'notary_id':self.identity,'signature':self.sign(f'CORIUM-EXODUS-SNSO-V1\ndefault\n{ph}\n{self.identity}')}
        self.assertEqual(self.rpc('ANNOUNCE_SNSO',notar)['status'],'success')
        self.assertEqual(self.rpc('GET_NOTARIZATIONS',ph)['status'],'success')
        with sqlite3.connect(self.forum) as db:db.execute("UPDATE exodus_notarizations SET signature='00'")
        self.assertEqual(self.rpc('GET_NOTARIZATIONS',ph)['status'],'error')
        self.assertEqual(self.rpc('GET_NOTARIZATIONS','bad')['status'],'error')
        self.forum.write_bytes(b'corrupt')
        self.assertEqual(self.rpc('GET_NOTARIZATIONS',ph)['status'],'error')

    def test_dht_store_authenticated_deduplicated_and_provider_discovery(self):
        digest='e'*64
        with sqlite3.connect(self.dht) as db:
            db.execute('INSERT INTO nodes(id,address_type,address,port,last_seen,distance) VALUES (?,?,?,?,?,?)',(self.identity,'ipv4','127.0.0.1',31337,int(time.time()),0))
        for _ in range(2):self.assertEqual(self.rpc('STORE',digest+' '+self.identity)['status'],'success')
        with sqlite3.connect(self.dht) as db:
            row=db.execute('SELECT nodes FROM chunks WHERE hash=?',(digest,)).fetchone()
            self.assertEqual(json.loads(row[0]),[self.identity])
        response=self.rpc('FIND_VALUE',digest)
        self.assertEqual(response['status'],'success');self.assertIn(self.identity+':ipv4:127.0.0.1:31337',response['data'])
        for payload in (digest+' '+('0'*64),digest,digest+' '+self.identity+' extra','not-a-hash '+self.identity):
            self.assertEqual(self.rpc('STORE',payload)['status'],'error')
        wrong=ec.generate_private_key(ec.SECP256K1())
        self.assertEqual(self.rpc('STORE',digest+' '+self.identity,wrong)['status'],'error')
        with sqlite3.connect(self.dht) as db:self.assertEqual(json.loads(db.execute('SELECT nodes FROM chunks WHERE hash=?',(digest,)).fetchone()[0]),[self.identity])

class StunDiscoveryTests(unittest.TestCase):
    def test_binding_xor_address_and_transaction_binding_over_udp(self):
        import socket, struct
        from unittest.mock import patch
        function=next(node for node in ast.parse(DAEMON).body if isinstance(node,ast.FunctionDef) and node.name=='discover_public_address')
        namespace={'socket':socket,'os':os,'time':time,'bilingual_print':lambda *args:None}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'gateway:stun','exec'),namespace)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0)); server.settimeout(5)
            def respond():
                request,peer=server.recvfrom(1024)
                cookie=0x2112A442
                address=bytes(a^b for a,b in zip(socket.inet_aton('198.18.0.1'),struct.pack('!I',cookie)))
                body=struct.pack('!HHBBH',0x20,8,0,1,54321^(cookie>>16))+address
                header=struct.pack('!HHI',0x101,len(body),cookie)
                # A response from the correct server with another transaction must be ignored.
                forged_address=bytes(a^b for a,b in zip(socket.inet_aton('203.0.113.9'),struct.pack('!I',cookie)))
                forged_body=struct.pack('!HHBBH',0x20,8,0,1,12345^(cookie>>16))+forged_address
                server.sendto(header+b'x'*12+forged_body,peer)
                server.sendto(header+request[8:20]+body,peer)
            thread=threading.Thread(target=respond,daemon=True); thread.start()
            with patch.dict(os.environ,CORIUM_STUN_SERVERS='127.0.0.1:'+str(server.getsockname()[1])):
                namespace['discover_public_address']()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual((namespace['PUBLIC_IP'],namespace['PUBLIC_PORT']),('198.18.0.1',54321))

if __name__=='__main__': unittest.main(verbosity=2)
