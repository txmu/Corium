#!/usr/bin/env python3
"""Regression tests execute the monolith with real schemas, signatures and files."""
from contextlib import closing
import copy,hashlib,json,os,pathlib,random,shlex,sqlite3,subprocess,tarfile,tempfile,unittest,io,signal
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_gateway import SOURCE,schema

class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='corium-core.');self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        network=getattr(self,'network_id','default')
        self.env=dict(os.environ,CORIUM_ROOT=str(self.root),CORIUM_NETWORK_ID_OVERRIDE=network,CORIUM_TEST_NO_DAEMONS='1')
        self.base=self.root/'var/lib/corix/networks'/network;self.etc=self.root/'etc/corix/networks'/network
        self.etc.mkdir(parents=True)
        self.chain=self.base/'blockchain/chain.db';self.forum=self.base/'forum/forum.db';self.dht=self.root/'var/lib/corix/p2p/dht.db'
        for path,name in [(self.chain,'_init_blockchain_db'),(self.forum,'_init_app_db'),(self.dht,'_init_dht_db')]:
            path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(path)) as db, db:db.executescript(schema(name))
        self.key=ec.generate_private_key(ec.SECP256K1())
        self.pem=self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
        self.identity=hashlib.sha256(self.pem.encode()).hexdigest()
        (self.etc/'identity.key').write_bytes(self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        (self.etc/'identity.key.pub').write_text(self.pem+'\n')
        payload=json.dumps([{'owner_id':self.identity,'domains':['corium']}],separators=(',',':'))
        genesis={'timestamp':0,'genesis_validators':[{'public_key':self.pem,'stake':1000}], 'nomen_genesis_commitment':{'reservations_payload':payload,'signature':self.sign(payload)}}
        (self.etc/'genesis.json').write_text(json.dumps(genesis))
        self.run_core('mkdir -p "$BUILD_TMP_DIR_BASE" "$INSTALLED_DB" "$P2P_DIR/objects"; forum_init; blockchain_create_genesis_block; _update_chain_state_cache')
    def sign(self,data):return self.key.sign(data.encode(),ec.ECDSA(hashes.SHA256())).hex()
    def run_core(self,script,ok=True):
        process=subprocess.Popen(['bash','-c','source '+shlex.quote(str(SOURCE))+'\n'+script],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try: stdout,stderr=process.communicate(timeout=getattr(self, "core_timeout", 90))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);stdout,stderr=process.communicate()
            self.fail('Core command timed out:\n'+script+'\n'+stdout+stderr)
        result=subprocess.CompletedProcess(process.args,process.returncode,stdout,stderr)
        if ok and result.returncode:self.fail('Real core command failed:\n'+script+'\n'+result.stdout+result.stderr)
        if not ok and not result.returncode:self.fail('Invalid input was accepted:\n'+script+'\n'+result.stdout+result.stderr)
        return result
    def semantic(self):return json.loads(self.run_core('_internal_semantic_state').stdout.splitlines()[-1])
    def snapshot(self,path='snapshot.json',height=0):
        output=self.root/path
        self.run_core('_internal_export_chain_state '+str(height)+' '+shlex.quote(str(output))+" ''")
        return json.loads(output.read_text())
    def import_snapshot(self,data,ok=True):
        file=self.root/'candidate.json';file.write_text(json.dumps(data,ensure_ascii=False))
        return self.run_core('_internal_import_phoenix_state '+shlex.quote(str(file)),ok)
    def add_empty_block(self,height,previous=None,timestamp=None,signature=None):
        with closing(sqlite3.connect(self.chain)) as db, db:
            if previous is None:previous=db.execute('SELECT hash FROM blocks WHERE height=?',(height-1,)).fetchone()[0]
            timestamp=height if timestamp is None else timestamp
            content=json.dumps({'height':height,'previous_hash':previous,'timestamp':timestamp,'transactions':[]},separators=(',',':'))
            blockhash=hashlib.sha256(content.encode()).hexdigest()
            db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)',(height,blockhash,previous,timestamp,self.identity,signature or self.sign(content),'[]',height*1000))
        return blockhash
class CoreTests(Fixture):
    def test_phoenix_deterministic_replay_from_corrupted_local_derived_state(self):
        first=self.snapshot()
        with sqlite3.connect(self.chain) as db:db.execute("UPDATE system_params SET param_value='poisoned'")
        with sqlite3.connect(self.forum) as db:db.execute("UPDATE nns_records SET target_hash='poisoned'")
        second=self.snapshot('second.json')
        self.assertEqual(first['state_root'],second['state_root'])
        self.assertEqual(first['state'],second['state'])
        self.assertEqual(second['state']['nns_records'][0]['target_hash'],'GENESIS_RESERVED_AWAITING_PUBLISH')
    def test_phoenix_destroy_restore_repeat_and_again(self):
        snapshot=self.snapshot();original=snapshot['state']
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM blocks');db.execute('DELETE FROM validators');db.execute('DELETE FROM system_params')
        with sqlite3.connect(self.forum) as db:db.execute('DELETE FROM nns_records')
        self.import_snapshot(snapshot)
        recovered=self.semantic()
        self.assertEqual({k:v for k,v in recovered['chain'].items() if k not in ('blocks','transactions')},original['chain_tables'])
        self.assertEqual(recovered['application'],original['application_tables'])
        # Another import into a non-empty chain must fail without changing any table.
        self.import_snapshot(snapshot,ok=False);self.assertEqual(self.semantic(),recovered)
        (self.etc/'genesis.json').write_text(json.dumps(snapshot))
        again=self.snapshot('again.json')
        self.assertEqual(again['state'],original)
    def test_phoenix_adversarial_fields_signature_types_and_duplicate_keys(self):
        original=self.snapshot();before=self.semantic()
        mutations=[('state_root','0'*64),('snapshot_signature','00'),('snapshot_public_key','bad'),('format','wrong')]
        for key,value in mutations:
            candidate=copy.deepcopy(original);candidate[key]=value;self.import_snapshot(candidate,False);self.assertEqual(self.semantic(),before)
        candidate=copy.deepcopy(original);candidate['state']['nns_records'][0]['owner_id']='0'*64
        self.import_snapshot(candidate,False);self.assertEqual(self.semantic(),before)
        # A correctly signed yet structurally invalid table cannot partially restore either DB.
        for mutate in [lambda c:c['state']['chain_tables'].pop('system_params'),lambda c:c['state']['chain_tables']['validators'][0].update(stake=True),lambda c:c['validators'].append(c['validators'][0])]:
            candidate=copy.deepcopy(original);mutate(candidate)
            del candidate['state_root'];del candidate['snapshot_signature']
            root=hashlib.sha256(json.dumps(candidate,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            candidate.update(state_root=root,snapshot_signature=self.sign(root))
            self.import_snapshot(candidate,False);self.assertEqual(self.semantic(),before)
    def test_phoenix_history_missing_parent_and_duplicate_transactions(self):
        self.add_empty_block(1);first=self.snapshot(height=1)
        self.assertEqual(first['recovery_anchor']['height'],1)
        with sqlite3.connect(self.chain) as db:db.execute("UPDATE blocks SET previous_hash=? WHERE height=1",('f'*64,))
        self.run_core('_internal_export_chain_state 1 "$CORIUM_ROOT/bad.json" ""',False)
        self.assertFalse((self.root/'bad.json').exists())
    def test_db_transaction_nested_rollback_and_wal(self):
        self.run_core('db_begin_transaction "$BLOCKCHAIN_DB" "$FORUM_DB"; db_begin_transaction "$BLOCKCHAIN_DB"; db_execute_safe "$BLOCKCHAIN_DB" "UPDATE system_params SET param_value=%s;" bad; db_execute_safe "$FORUM_DB" "DELETE FROM nns_records;"; db_commit_transaction "$BLOCKCHAIN_DB"; db_rollback_transaction "$BLOCKCHAIN_DB" "$FORUM_DB"')
        state=self.semantic();self.assertNotEqual(state['chain']['system_params'][0]['param_value'],'bad');self.assertEqual(len(state['application']['nns_records']),1)
    def test_binary_chunks_exact_and_corruption_preserves_output(self):
        content=bytes(range(256))*20+b'\x00tail\n\n';(self.root/'input.bin').write_bytes(content)
        result=self.run_core('P2P_CHUNK_SIZE=1024; manifest=$(p2p_split_file "$CORIUM_ROOT/input.bin"); cp "$manifest" "$CORIUM_ROOT/manifest.json"; p2p_reconstruct_file "$manifest" "$CORIUM_ROOT/output.bin"')
        self.assertEqual((self.root/'output.bin').read_bytes(),content)
        manifest=json.loads((self.root/'manifest.json').read_text())
        obj=self.root/'var/lib/corix/p2p/objects'/manifest['chunks'][0];obj.write_bytes(b'corrupt')
        self.run_core('p2p_reconstruct_file "$CORIUM_ROOT/manifest.json" "$CORIUM_ROOT/output.bin"',False)
        self.assertEqual((self.root/'output.bin').read_bytes(),content)
    def test_empty_file_manifest_and_malformed_manifest(self):
        (self.root/'empty').touch();self.run_core('manifest=$(p2p_split_file "$CORIUM_ROOT/empty"); p2p_reconstruct_file "$manifest" "$CORIUM_ROOT/out"')
        self.assertEqual((self.root/'out').read_bytes(),b'')
        (self.root/'bad.json').write_text('{"size":1,"chunk_size":0,"chunks":[]}')
        self.run_core('p2p_reconstruct_file "$CORIUM_ROOT/bad.json" "$CORIUM_ROOT/out"',False)
    def test_archive_traversal_symlink_member_and_duplicate_rejected(self):
        for index,names in enumerate([['../escape'],['/absolute'],['safe','safe'],['link/evil']]):
            archive=self.root/f'bad{index}.tar'
            with tarfile.open(archive,'w') as tf:
                if index==3:
                    entry=tarfile.TarInfo('link');entry.type=tarfile.SYMTYPE;entry.linkname='/tmp';tf.addfile(entry)
                for name in names:
                    entry=tarfile.TarInfo(name);entry.size=1;tf.addfile(entry,io.BytesIO(b'x'))
            self.run_core('_validate_archive '+shlex.quote(str(archive)),False)
        archive=self.root/'safe.tar'
        with tarfile.open(archive,'w') as tf:
            entry=tarfile.TarInfo('usr/bin/test');entry.size=3;tf.addfile(entry,io.BytesIO(b'ok\n'))
        self.run_core('_validate_archive '+shlex.quote(str(archive)))
    def test_package_ownership_exact_paths(self):
        directory=self.base/'installed/pkg';directory.mkdir(parents=True);(directory/'files').write_text('usr/bin/tool\n')
        self.run_core('db_owns_file usr/bin/tool')
        self.run_core('db_owns_file usr/bin/not-owned',False)
    def test_canonical_hash_does_not_depend_on_same_named_local_file(self):
        payload={'nickname':'canonical|🙂'};tx=self.put_transaction('set_nickname',payload)
        body=json.dumps({'type':'set_nickname','data':payload,'timestamp':1},ensure_ascii=False,separators=(',',':'))
        (self.root/body).write_text('unrelated local file')
        self.run_core('cd "$CORIUM_ROOT"; declare -A track=() cache=(); _validate_single_transaction '+tx+' 127.0.0.1 1 2 track cache')
        (self.root/'108|salt').write_text('unrelated blind-hash file')
        expected=hashlib.sha256(b'108|salt').hexdigest()
        self.assertEqual(self.run_core('cd "$CORIUM_ROOT"; _internal_hash_text "108|salt"').stdout.strip(),expected)

    def test_sql_integer_boundaries_and_injection(self):
        for value in ['1; DROP TABLE validators;',str(2**63),'1.5','true']:
            self.run_core('_sql_safe_integer '+shlex.quote(value),False)
        self.run_core('_sql_safe_integer -9223372036854775808; _sql_safe_integer 9223372036854775807')
        self.assertEqual(self.run_core('_sql_safe_integer 01').stdout.strip(),'1')
        before=self.semantic();self.run_core('db_query_safe "$BLOCKCHAIN_DB" "SELECT stake FROM validators WHERE public_key_hash=%s;" "x\x27 OR 1=1 --"');self.assertEqual(before,self.semantic())
    def test_network_namespace_validation(self):
        env=dict(self.env,CORIUM_NETWORK_ID_OVERRIDE='../escape')
        result=subprocess.run([str(SOURCE),'--version'],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
    def test_phoenix_seeded_derived_chaos(self):
        seed=int(os.environ.get('CORIUM_TEST_SEED','108'));rng=random.Random(seed);expected=self.snapshot();trace=[]
        for iteration in range(int(os.environ.get('CORIUM_CHAOS_ROUNDS','4'))):
            operation=rng.choice(['params','nns','both']);trace.append(operation)
            with sqlite3.connect(self.chain) as db:
                if operation in ('params','both'):db.execute('UPDATE system_params SET param_value=?',(str(rng.getrandbits(64)),))
            with sqlite3.connect(self.forum) as db:
                if operation in ('nns','both'):db.execute('UPDATE nns_records SET target_hash=?',(str(rng.getrandbits(64)),))
            candidate=self.snapshot(f'chaos-{iteration}.json')
            self.assertEqual(candidate['state'],expected['state'],f'seed={seed} trace={trace}')
            self.assertEqual(candidate['state_root'],expected['state_root'],f'seed={seed} trace={trace}')

    def test_metadata_multiline_unicode_missing_fields_and_malformed(self):
        build=self.root/'package.build';build.write_text('pkgname="hello"\npkgver=1\npkgdesc="中文 | sample"\ndepends=(\n "dev/a"\n "dev/b:2"\n)\nsource=()\nbuild() {\n  echo ok\n}\n')
        parsed=dict(line.split('=',1) for line in self.run_core('_parse_build_file "$CORIUM_ROOT/package.build"').stdout.splitlines())
        self.assertEqual(parsed['source'],'');self.assertEqual(parsed['depends'],'dev/a dev/b:2');self.assertEqual(parsed['slot'],'0');self.assertEqual(parsed['pkgdesc'],'中文 | sample')
        build.write_text('pkgname="hello\n');self.run_core('_parse_build_file "$CORIUM_ROOT/package.build"',False)
    def test_dependency_installed_duplicate_missing_cycle_and_external(self):
        cache=self.root/'var/cache/corix/metadata/meta.db';cache.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(cache) as db:
            db.execute('CREATE TABLE packages(id TEXT PRIMARY KEY,version TEXT,depends TEXT,makedepends TEXT,source_repo TEXT)')
            db.executemany('INSERT INTO packages VALUES (?,\'1\',?,?,\'test\')',[('dev/a:0','dev/b dev/b','dev/b'),('dev/b:0','','')])
        order=self.run_core('dep_resolve_topological dev/a').stdout.strip().split()
        self.assertEqual(order,['dev/b:0','dev/a:0'])
        installed=self.base/'installed/dev_b-0';installed.mkdir(parents=True)
        order=self.run_core('dep_resolve_topological dev/a').stdout.strip().split();self.assertEqual(order,['dev/a:0'])
        installed.rmdir()
        with sqlite3.connect(cache) as db:db.execute("UPDATE packages SET depends='dev/a' WHERE id='dev/b:0'")
        self.run_core('dep_resolve_topological dev/a',False)
        with sqlite3.connect(cache) as db:db.execute("UPDATE packages SET depends='dev/missing',makedepends='' WHERE id='dev/a:0'")
        self.run_core('dep_resolve_topological dev/a',False)
        external=self.base/'external';external.mkdir();(external/'test.db').write_text('dev/missing:0 1\n')
        self.assertEqual(self.run_core('dep_resolve_topological dev/a').stdout.strip(),'dev/a:0')
    def test_filesystem_transaction_exit_restores_files_world_and_database(self):
        target=self.root/'usr/bin/tool';target.parent.mkdir(parents=True);target.write_bytes(b'original\x00\n')
        (self.etc/'world').write_text('dev/tool:0\n')
        (self.root/'manifest').write_text('usr/bin/tool\nnew/created\n')
        state=self.semantic()
        self.run_core('_begin_transaction "$INSTALLED_DB"; _transaction_stage_files "$CORIUM_ROOT/manifest"; printf changed > "$CORIUM_ROOT/usr/bin/tool"; mkdir -p "$CORIUM_ROOT/new"; printf new > "$CORIUM_ROOT/new/created"; printf changed > "$WORLD_FILE"; db_execute_safe "$BLOCKCHAIN_DB" "DELETE FROM validators;"; exit 1',False)
        self.assertEqual(target.read_bytes(),b'original\x00\n');self.assertFalse((self.root/'new').exists());self.assertEqual((self.etc/'world').read_text(),'dev/tool:0\n');self.assertEqual(self.semantic(),state)
    def test_remove_honors_root_and_complete_package_state(self):
        installed=self.base/'installed/dev_tool-0';installed.mkdir(parents=True)
        for name,value in {'files':'usr/bin/tool\n','name':'dev/tool\n','slot':'0\n','version':'1\n','dependencies':''}.items():(installed/name).write_text(value)
        target=self.root/'usr/bin/tool';target.parent.mkdir(parents=True);target.write_text('tool')
        (self.etc/'world').write_text('dev/tool:0\ndev/other:0\n')
        self.run_core('corix_remove dev/tool:0 <<< y')
        self.assertFalse(target.exists());self.assertFalse(installed.exists());self.assertEqual((self.etc/'world').read_text(),'dev/other:0\n')
    def test_acl_unicode_quotes_malformed_denial_and_owner(self):
        permission='write" | 中文'
        with sqlite3.connect(self.forum) as db:db.execute('INSERT INTO acl_state VALUES (?,?,?)',('acl',self.identity,json.dumps([permission],ensure_ascii=False)))
        self.run_core('_is_authorized_by_acl acl '+self.identity+' '+shlex.quote(permission))
        self.run_core('_is_authorized_by_acl acl '+self.identity+' admin',False)
        for value in ['null','{}','[true]','not-json']:
            with sqlite3.connect(self.forum) as db:db.execute('UPDATE acl_state SET permissions=?',(value,))
            self.run_core('_is_authorized_by_acl acl '+self.identity+' admin',False)
        with sqlite3.connect(self.forum) as db:db.execute('UPDATE acl_state SET permissions=\'["owner"]\'')
        self.run_core('_is_authorized_by_acl acl '+self.identity+' write')
    def test_backup_destroy_restore_semantics_repeat_and_corruption(self):
        expected=self.semantic()
        self.run_core('corix_backup_create "$CORIUM_ROOT/backup.tar.gz"')
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM validators')
        with sqlite3.connect(self.forum) as db:db.execute('DELETE FROM nns_records')
        self.run_core('corix_backup_restore "$CORIUM_ROOT/backup.tar.gz" <<< y')
        self.assertEqual(self.semantic(),expected)
        self.run_core('corix_backup_restore "$CORIUM_ROOT/backup.tar.gz" <<< y')
        self.assertEqual(self.semantic(),expected)
        (self.root/'bad.tar.gz').write_bytes(b'corrupt')
        self.run_core('corix_backup_restore "$CORIUM_ROOT/bad.tar.gz" <<< y',False);self.assertEqual(self.semantic(),expected)
    def test_history_forged_block_signature_rejected_without_output(self):
        self.add_empty_block(1,signature='00')
        self.run_core('_internal_export_chain_state 1 "$CORIUM_ROOT/bad.json" ""',False)
        self.assertFalse((self.root/'bad.json').exists())

    def test_lottery_full_pem_and_mining_validated_transaction(self):
        self.assertEqual(self.run_core('blockchain_get_next_validator').stdout.strip(),self.pem)
        self.run_core('blockchain_create_transaction set_nickname \'{"nickname":"中文|🙂"}\' >/dev/null; blockchain_mine_block')
        state=self.semantic()
        self.assertEqual(len(state['chain']['blocks']),2)
        latest=max(state['chain']['blocks'],key=lambda row:row['height'])
        self.assertEqual(latest['height'],1);self.assertEqual(latest['total_weight'],1000)
        self.assertEqual(len(state['chain']['transactions']),1)
        self.assertEqual(state['application']['identity_cache'][0]['nickname'],'中文|🙂')
        snapshot=self.snapshot(height=1);self.assertEqual(snapshot['state']['application_tables']['identity_cache'],state['application']['identity_cache'])
    def test_invalid_mempool_cannot_mine_and_nested_subshell_cannot_commit_parent(self):
        self.run_core('blockchain_create_transaction set_nickname \'{"nickname":"valid"}\' >/dev/null')
        with sqlite3.connect(self.chain) as db:db.execute('UPDATE transactions SET signature=\'00\'')
        expected=self.semantic();self.run_core('blockchain_mine_block',False);self.assertEqual(self.semantic(),expected)
        self.run_core('db_begin_transaction "$BLOCKCHAIN_DB"; db_execute_safe "$BLOCKCHAIN_DB" "DELETE FROM validators;"; ignored=$(db_commit_transaction "$BLOCKCHAIN_DB"); db_rollback_transaction "$BLOCKCHAIN_DB"')
        self.assertEqual(self.semantic(),expected)
    def test_exodus_real_proposal_notarization_quorum_and_forged_record(self):
        result=self.run_core('corix_exodus propose-snapshot 0')
        with sqlite3.connect(self.forum) as db:proposal=db.execute('SELECT proposal_hash FROM exodus_proposals').fetchone()[0]
        self.run_core('corix_exodus notarize '+proposal)
        snapshot=self.snapshot()
        result=self.run_core('_internal_verify_exodus_quorum '+proposal+' "$CORIUM_ROOT/snapshot.json"')
        self.assertTrue(json.loads(result.stdout)['quorum'])
        with sqlite3.connect(self.forum) as db:db.execute('UPDATE exodus_notarizations SET signature=\'00\'')
        self.run_core('_internal_verify_exodus_quorum '+proposal+' "$CORIUM_ROOT/snapshot.json"',False)
    def test_snapshot_rsync_historical_db_and_rollback(self):
        (self.etc/'world').write_text('')
        expected=self.semantic()
        self.run_core('corix_snapshot_create baseline')
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM validators')
        self.run_core('corix_snapshot_rollback baseline <<< y')
        self.assertEqual(self.semantic(),expected)
        self.run_core('corix_snapshot_delete ../escape <<< y',False)
    def test_filesystem_nested_transaction_commits_only_outermost(self):
        (self.etc/'world').write_text('')
        self.run_core('_begin_transaction "$INSTALLED_DB"; _begin_transaction "$INSTALLED_DB"; _commit_transaction; [ -n "$CURRENT_TRANSACTION_BACKUP_PATH" ]; _commit_transaction; [ -z "$CURRENT_TRANSACTION_BACKUP_PATH" ]')

    def test_governance_full_pem_duplicate_votes_threshold_and_json_fields(self):
        proposal='c'*64;target='d'*64
        with sqlite3.connect(self.chain) as db:
            db.execute('UPDATE validators SET stake=?',(2**62,))
            db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)',(proposal,'validator_propose_removal',json.dumps({'target_pubkey_hash':target,'note':'中文|line\\n🙂'}),'00',self.pem,0,1))
            for index in range(2):
                db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)',(str(index)*64,'validator_vote_removal',json.dumps({'proposal_tx_hash':proposal,'vote':'yes'}),'00',self.pem,2,2))
        self.run_core('_protocol_tally_votes_and_schedule_changes 101')
        with sqlite3.connect(self.chain) as db:
            row=db.execute('SELECT enactment_height,data FROM scheduled_state_changes').fetchone()
            self.assertEqual(row[0],111);self.assertIn('中文|',json.loads(row[1])['note'])
            db.execute('INSERT INTO validators(public_key,public_key_hash,stake) VALUES (?,?,?)',('target',target,1))
        self.run_core('_protocol_execute_scheduled_changes 111')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT stake FROM validators WHERE public_key_hash=?',(target,)).fetchone()[0],0)
        # Duplicate votes must not turn 1/2 of total stake into consensus.
        with sqlite3.connect(self.chain) as db:
            db.execute('DELETE FROM scheduled_state_changes');db.execute('UPDATE validators SET stake=100')
        self.run_core('_protocol_tally_votes_and_schedule_changes 101')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT count(*) FROM scheduled_state_changes').fetchone()[0],0)

    def test_metadata_cache_invalid_build_preserves_previous_rows(self):
        repo=self.root/'repo/dev/hello';repo.mkdir(parents=True)
        build=repo/'hello.build';build.write_text('pkgname=hello\npkgver=1\nbuild() {\n  pkgname=runtime_name\n}\n')
        configs=self.etc/'repos.conf.d';configs.mkdir()
        (configs/'local.conf').write_text('type=local\npath='+str(self.root/'repo')+'\n')
        self.run_core('_update_metadata_cache')
        cache=self.root/'var/cache/corix/metadata/meta.db'
        with sqlite3.connect(cache) as db:expected=db.execute('SELECT * FROM packages').fetchall()
        self.assertEqual(len(expected),1)
        build.write_text('pkgname="unterminated\n')
        self.run_core('_update_metadata_cache',False)
        with sqlite3.connect(cache) as db:self.assertEqual(db.execute('SELECT * FROM packages').fetchall(),expected)

    def test_identity_lookup_rejects_poisoned_cache_and_unjails_at_boundary(self):
        cache=self.base/'forum/pubkeys';cache.mkdir(parents=True,exist_ok=True)
        cached=cache/(self.identity+'.pub');cached.write_text('forged')
        result=self.run_core('_get_identity_pubkey '+self.identity)
        self.assertEqual(pathlib.Path(result.stdout.strip().splitlines()[-1]).read_text().rstrip(),self.pem)
        self.run_core('_get_identity_pubkey '+('0'*64),False)
        with sqlite3.connect(self.chain) as db:db.execute("UPDATE validators SET status='jailed',jailed_until_height=4")
        self.run_core('_slashing_check_for_jailed_validators 3')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT status FROM validators').fetchone()[0],'jailed')
        self.run_core('_slashing_check_for_jailed_validators 4')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT status FROM validators').fetchone()[0],'active')

    def test_state_prover_odd_merkle_and_existing_ibc_command(self):
        prover=self.run_core('_corix_get_state_prover_source').stdout
        ns={'__name__':'merkle_test'};exec(compile(prover,'embedded-prover','exec'),ns)
        leaves=[hashlib.sha256(str(i).encode()).hexdigest() for i in range(5)]
        tree=ns['build_merkle_tree'](leaves)
        for leaf in leaves:
            value=leaf
            for item in ns['get_merkle_proof'](tree,leaf):
                value=hashlib.sha256(((item['hash']+value) if item['position']=='left' else (value+item['hash'])).encode()).hexdigest()
            self.assertEqual(value,tree[-1][0])
        output=self.run_core('_internal_ibc_generate_state_proof 0 nns_record '+self.identity).stdout
        proof=json.loads(output);self.assertEqual(proof['asset_data']['owner_id'],self.identity)

    def put_transaction(self,kind,data,timestamp=1):
        payload=json.dumps({'type':kind,'data':data,'timestamp':timestamp},ensure_ascii=False,separators=(',',':'))
        tx=hashlib.sha256(payload.encode()).hexdigest()
        with sqlite3.connect(self.chain) as db:db.execute('INSERT OR REPLACE INTO transactions VALUES (?,?,?,?,?,?,NULL)',(tx,kind,json.dumps(data,ensure_ascii=False,separators=(',',':')),self.sign(payload),self.pem,timestamp))
        return tx
    def validate_transaction(self,tx,height=2,ok=True):
        return self.run_core('declare -A track=() cache=(); _validate_single_transaction '+tx+' 127.0.0.1 1 '+str(height)+' track cache',ok)
    def test_governance_vote_authorization_stale_duplicate_and_intrablock(self):
        proposal=self.put_transaction('validator_propose_removal',{'target_pubkey_hash':'d'*64})
        with sqlite3.connect(self.chain) as db:db.execute('UPDATE transactions SET block_height=1 WHERE hash=?',(proposal,))
        vote=self.put_transaction('validator_vote_removal',{'proposal_tx_hash':proposal,'vote':'yes'},2)
        self.validate_transaction(vote)
        self.validate_transaction(vote,102,False)
        invalid=self.put_transaction('validator_vote_removal',{'proposal_tx_hash':proposal,'vote':'maybe'},3);self.validate_transaction(invalid,ok=False)
        self.run_core('declare -A track=() cache=(); _validate_single_transaction '+vote+' 127.0.0.1 1 2 track cache; _validate_single_transaction '+vote+' 127.0.0.1 1 2 track cache',False)
        with sqlite3.connect(self.chain) as db:db.execute('UPDATE transactions SET block_height=2 WHERE hash=?',(vote,))
        duplicate=self.put_transaction('validator_vote_removal',{'proposal_tx_hash':proposal,'vote':'yes'},4);self.validate_transaction(duplicate,3,False)
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM validators')
        self.validate_transaction(vote,ok=False)
    def test_agent_key_binding_acl_escalation_and_member_leave(self):
        invalid=self.put_transaction('agent_create',{'agent_id':'a'*64,'agent_pubkey':self.pem,'pkg_id':'mods/agent:0'})
        self.validate_transaction(invalid,ok=False)
        valid=self.put_transaction('agent_create',{'agent_id':self.identity,'agent_pubkey':self.pem,'pkg_id':'mods/agent:0'},2)
        self.validate_transaction(valid)
        self.run_core('declare -A track=() cache=(); _validate_single_transaction '+valid+' 127.0.0.1 1 2 track cache; _validate_single_transaction '+valid+' 127.0.0.1 1 2 track cache',False)
        with sqlite3.connect(self.forum) as db:db.execute('INSERT INTO acl_state VALUES (?,?,?)',('acl',self.identity,'["admin","member"]'))
        grant=self.put_transaction('acl_grant',{'acl_id':'acl','grantee_id':'b'*64,'permissions':['owner']},3);self.validate_transaction(grant,ok=False)
        with sqlite3.connect(self.forum) as db:db.execute("UPDATE acl_state SET permissions='[\"owner\"]'")
        self.validate_transaction(grant)
        with sqlite3.connect(self.forum) as db:db.execute("UPDATE acl_state SET permissions='[\"member\"]'")
        leave=self.put_transaction('acl_revoke',{'acl_id':'acl','grantee_id':self.identity,'permissions':['member']},4);self.validate_transaction(leave)
        kick=self.put_transaction('acl_revoke',{'acl_id':'acl','grantee_id':'b'*64,'permissions':['member']},5);self.validate_transaction(kick,ok=False)

    def test_cbb_game_authenticated_turns_terminal_and_forgery(self):
        import time
        other=ec.generate_private_key(ec.SECP256K1());pem=other.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n');ident=hashlib.sha256(pem.encode()).hexdigest()
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO validators(public_key,public_key_hash,stake) VALUES (?,?,1000)',(pem,ident))
        game='game-regression';ts=int(time.time());seq=0
        def post(author,key,action,payload,forged=False):
            nonlocal seq
            message=f'GAME:TICTACTOE|ID:{game}|ACTION:{action}|PAYLOAD:{payload}'
            canonical=f'CORIUM-CBB-V1\ndefault\n{author}\n{ts+seq}\n{message}'
            signature='00' if forged else key.sign(canonical.encode(),ec.ECDSA(hashes.SHA256())).hex()
            with sqlite3.connect(self.forum) as db:db.execute('INSERT INTO cbb_messages VALUES (?,?,?,?,?,?)',(hashlib.sha256(canonical.encode()).hexdigest(),author,ts+seq,message,signature,ts+seq+86400))
            seq+=1
        post(self.identity,self.key,'NEW',self.identity+',')
        post(ident,other,'JOIN',ident)
        post(ident,other,'MOVE',self.identity+',1') # Payload spoof cannot move for X.
        post(self.identity,self.key,'MOVE',self.identity+',9',True)
        for author,key,pos in [(self.identity,self.key,1),(ident,other,4),(self.identity,self.key,2),(ident,other,5),(self.identity,self.key,3)]:post(author,key,'MOVE',author+','+str(pos))
        post(ident,other,'MOVE',ident+',6') # Terminal board stays unchanged.
        state=self.run_core('_cbb_game_get_state '+game).stdout.strip().split('|')
        self.assertEqual(state,[self.identity,ident,'XXXOO----','O','WIN_X'])
        self.assertEqual(self.run_core('_cbb_game_get_state '+game).stdout.strip().split('|'),state)
        self.run_core("_cbb_game_get_state "+shlex.quote("game-x' OR 1=1 --"),False)

    def test_forum_signed_publish_sync_repair_legacy_and_forgeries(self):
        body='正文|🙂\n'+'z'*2048
        attachment=self.root/'quote"|附件.bin';attachment.write_bytes(b'\x00attachment\xff')
        self.run_core('P2P_CHUNK_SIZE=128; forum_create_topic '+shlex.quote('题目|"🙂')+' '+shlex.quote(body)+' '+shlex.quote(str(attachment)))
        with sqlite3.connect(self.forum) as db:
            topic=db.execute('SELECT id,author,content_hash,attachment_hash FROM topics').fetchone()
        self.assertEqual(topic[1],self.identity)
        self.run_core('P2P_CHUNK_SIZE=128; forum_create_post '+topic[0]+' '+shlex.quote('回复|🙂')+' '+shlex.quote(str(attachment)))
        # Discovery beacons must be valid canonical transactions and mine/replay normally.
        self.run_core('blockchain_mine_block; _internal_rebuild_derived_state')
        manifests=self.base/'forum/manifests';objects=self.base/'forum/objects'
        with sqlite3.connect(self.forum) as db:
            post=db.execute('SELECT id FROM posts').fetchone()[0];expected=db.execute('SELECT id,title,author,content_hash,attachment_hash FROM topics').fetchall()
            db.execute('DELETE FROM topics');db.execute('DELETE FROM posts');db.execute('DELETE FROM objects')
        self.run_core('forum_sync')
        with sqlite3.connect(self.forum) as db:
            self.assertEqual(db.execute('SELECT id,title,author,content_hash,attachment_hash FROM topics').fetchall(),expected)
            self.assertEqual(db.execute('SELECT id,topic_id FROM posts').fetchall(),[(post,topic[0])]);self.assertGreater(db.execute('SELECT COUNT(*) FROM objects').fetchone()[0],0)
        # An existing DB row must not skip repair of a missing body object.
        backup=self.root/'body-provider';backup.write_bytes(body.encode());(objects/topic[2]).unlink()
        self.run_core('dht_store_chunk '+topic[2]+' '+shlex.quote(str(backup))+' 0 '+str(backup.stat().st_size)+'; forum_sync')
        self.assertEqual((objects/topic[2]).read_bytes(),body.encode())
        # Missing manifest file is genuinely retrieved by its existing full-object ID.
        manifest_source=self.root/'manifest-provider';manifest_source.write_bytes((manifests/(topic[0]+'.json')).read_bytes());(manifests/(topic[0]+'.json')).unlink()
        self.run_core('dht_store_chunk '+topic[0]+' '+str(manifest_source)+' 0 '+str(manifest_source.stat().st_size)+'; forum_sync')
        # Recreate the original post writer's whitespace signature and echo newline.
        old='{{\n  "topic_id": "{}",\n  "author": "{}",\n  "timestamp": 7,\n  "content_hash": "{}",\n  "attachment_hash": "",\n  "attachment_name": ""\n}}'.format(topic[0],self.identity,topic[2])
        legacy=old[:-1]+', "signature": "'+self.sign(old)+'"\n}'
        legacy_id=hashlib.sha256(legacy.encode()).hexdigest();(manifests/(legacy_id+'.json')).write_text(legacy+'\n')
        def beacon(item,ts):
            tx=self.put_transaction('forum',{'type':'forum_post','post_id':item,'topic_id':topic[0]},ts)
            with sqlite3.connect(self.chain) as db:db.execute('UPDATE transactions SET block_height=1 WHERE hash=?',(tx,))
        beacon(legacy_id,8);self.run_core('forum_sync')
        with sqlite3.connect(self.forum) as db:self.assertIsNotNone(db.execute('SELECT id FROM posts WHERE id=?',(legacy_id,)).fetchone())
        # Original forum authors included the PEM newline; their genuine signatures remain valid.
        legacy_author=hashlib.sha256((self.pem+'\n').encode()).hexdigest()
        (self.base/'forum/pubkeys'/(legacy_author+'.pub')).write_text(self.pem+'\n')
        old_author_body=old.replace(self.identity,legacy_author)
        old_author_manifest=old_author_body[:-1]+', "signature": "'+self.sign(old_author_body)+'"\n}'
        old_author_id=hashlib.sha256(old_author_manifest.encode()).hexdigest();(manifests/(old_author_id+'.json')).write_text(old_author_manifest+'\n');beacon(old_author_id,9)
        self.run_core('forum_sync')
        with sqlite3.connect(self.forum) as db:self.assertEqual(db.execute('SELECT author FROM posts WHERE id=?',(old_author_id,)).fetchone()[0],legacy_author)
        # A hash-valid manifest with a forged signature cannot pollute trusted rows.
        bad=json.loads((manifests/(post+'.json')).read_text());bad['signature']='00';raw=json.dumps(bad,ensure_ascii=False);bad_id=hashlib.sha256(raw.encode()).hexdigest();(manifests/(bad_id+'.json')).write_text(raw);beacon(bad_id,9)
        with sqlite3.connect(self.forum) as db:before=db.execute('SELECT * FROM posts ORDER BY id').fetchall()
        self.run_core('forum_sync',False)
        with sqlite3.connect(self.forum) as db:self.assertEqual(db.execute('SELECT * FROM posts ORDER BY id').fetchall(),before)
        self.run_core('forum_fetch_object '+shlex.quote('../escape')+' "$FORUM_OBJECTS_DIR"',False)

    def test_build_metadata_version_and_slot_path_traversal_rejected(self):
        build=self.root/'component.build'
        for field,value in [('pkgver','../../escape'),('pkgver','..'),('pkgname','../escape'),('slot','../../../escape'),('slot','0/..')]:
            build.write_text('pkgname=component\npkgver=1\nslot=0\n'+field+'="'+value+'"\n')
            self.run_core('_parse_build_file '+str(build),False)
        build.write_text('pkgname=component\npkgver="版本-1+build"\nslot=0/1\n')
        values=dict(line.split('=',1) for line in self.run_core('_parse_build_file '+str(build)).stdout.splitlines());self.assertEqual(values['pkgver'],'版本-1+build');self.assertEqual(values['slot'],'0/1')

    def test_repository_build_lookup_spaces_remote_and_stale_cache(self):
        configs=self.etc/'repos.conf.d';configs.mkdir()
        repo=self.root/'repository with spaces/dev/hello';repo.mkdir(parents=True);build=repo/'hello.build';build.write_text('pkgname=hello\npkgver=1\n')
        (configs/'local space.conf').write_text('type=local\npath="'+str(self.root/'repository with spaces')+'"\n')
        result=self.run_core('find_package_build_file dev/hello:0').stdout.strip();self.assertEqual(result,str(build))
        remote=self.root/'usr/corix/repos/networks/default/remote repo/dev/other';remote.mkdir(parents=True);other=remote/'other.build';other.write_text('pkgname=other\npkgver=1\n')
        (configs/'remote repo.conf').write_text('type=p2p\nroot_hash='+'a'*64+'\n')
        self.assertEqual(self.run_core('find_package_build_file dev/other:0').stdout.strip(),str(other))
        self.run_core('mkdir -p "$METADATA_CACHE_DIR/paths/dev"; printf /nonexistent > "$METADATA_CACHE_DIR/paths/dev/hello"')
        self.assertEqual(self.run_core('find_package_build_file dev/hello:0').stdout.strip(),str(build))

    def test_governance_native_proposal_vote_mining_and_fresh_replay(self):
        public=self.root/'candidate.pub';public.write_text(self.pem+'\n')
        self.run_core('corix_validator_propose_add '+str(public)+' 1000; blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:proposal=db.execute("SELECT hash FROM transactions WHERE type='validator_propose_addition' AND block_height=1").fetchone()[0]
        self.run_core('corix_validator_vote '+proposal+' yes; blockchain_mine_block')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions WHERE type='validator_vote_addition' AND block_height=2").fetchone()[0],1)
        expected=self.semantic();self.run_core('_internal_rebuild_derived_state');self.assertEqual(self.semantic(),expected)
        recovered=self.snapshot('governance-replay.json',2)['state'];self.assertEqual(recovered['application_tables'],expected['application'])

    def test_validator_selection_is_readonly_with_scheduled_change_and_unjail(self):
        with sqlite3.connect(self.chain) as db:
            db.execute("UPDATE validators SET status='jailed',jailed_until_height=1")
            db.execute('INSERT INTO scheduled_state_changes VALUES (?,?,?,?)',('c'*64,1,'validator_propose_addition',json.dumps({'target_pubkey':self.pem,'initial_stake':2000})))
        before=self.semantic();self.assertEqual(self.run_core('blockchain_get_next_validator').stdout.strip(),self.pem);self.assertEqual(self.semantic(),before)
        self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"unjail\"}' >/dev/null; blockchain_mine_block")
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT status FROM validators').fetchone()[0],'active')

    def test_template_schema_failure_restores_files_installed_and_chain(self):
        from test_pgp_fixture import OpenPGPFixture
        signer=OpenPGPFixture();zone=self.etc/'trust_zones/apps';zone.mkdir(parents=True);(zone/'keyring.gpg').write_bytes(signer.keyring())
        (self.etc/'world').write_text('')
        archive=self.root/'template.tar.gz'
        with tarfile.open(archive,'w:gz') as tf:
            for name,data in {'.corium/template.build':b'pkgname=existing\npkgver=1\nslot=0\n','.corium/manifest.files':b'engine.txt\nschema/001.sql\n','engine.txt':b'existing engine','schema/001.sql':b'CREATE TABLE migration_partial(value TEXT); INVALID SQL;\n'}.items():
                entry=tarfile.TarInfo(name);entry.size=len(data);tf.addfile(entry,io.BytesIO(data))
        digest=hashlib.sha256(archive.read_bytes()).hexdigest();cache=self.root/'var/cache/corix/binaries';cache.mkdir(parents=True,exist_ok=True);cached=cache/(digest+'.tar.gz');cached.write_bytes(archive.read_bytes())
        import base64
        change={'template_name':'existing-template','pkg_id':'apps/existing:0','package_hash':digest,'manifest_hash':digest,'developer_signature':base64.b64encode(signer.signature(archive.read_bytes())).decode(),'developer_id':self.identity,'handles_tx_types':[]}
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO scheduled_state_changes VALUES (?,?,?,?)',('c'*64,1,'propose_app_template',json.dumps(change)))
        self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"activation-test\"}' >/dev/null")
        before=self.semantic();self.run_core('blockchain_mine_block',False)
        self.assertEqual(self.semantic(),before);self.assertFalse((self.base/'app_templates/apps_existing/1').exists());self.assertFalse((self.base/'installed/apps_existing-0').exists())
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='migration_partial'").fetchone()[0],0)

    def test_scheduled_template_missing_data_blocks_atomic_transition(self):
        change={'template_name':'existing-template','pkg_id':'apps/existing:0','package_hash':'a'*64,'manifest_hash':'b'*64,'developer_signature':'missing','developer_id':self.identity,'handles_tx_types':[]}
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO scheduled_state_changes VALUES (?,?,?,?)',('c'*64,1,'propose_app_template',json.dumps(change)))
        self.run_core("blockchain_create_transaction set_nickname '{\"nickname\":\"scheduled-test\"}' >/dev/null")
        before=self.semantic()
        self.run_core('blockchain_mine_block',False)
        self.assertEqual(self.semantic(),before)
        with sqlite3.connect(self.chain) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_app_templates').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scheduled_state_changes').fetchone()[0],1)

    def test_metadata_cache_preserves_caller_variables(self):
        self.run_core('mkdir -p "$REPOS_CONF_DIR"; build_file=caller-build; repo_conf=caller-repo; _update_metadata_cache; [ "$build_file" = caller-build ] && [ "$repo_conf" = caller-repo ]')

    def test_signed_package_install_conflict_corruption_postinstall_failure_and_remove(self):
        import platform
        gpg=self.root/'gnupg';gpg.mkdir(mode=0o700);self.env['GNUPGHOME']=str(gpg)
        from test_pgp_fixture import OpenPGPFixture
        signer=OpenPGPFixture()
        zone=self.etc/'trust_zones/dev';zone.mkdir(parents=True)
        (zone/'keyring.gpg').write_bytes(signer.keyring())
        repo=self.root/'repo/dev/hello';repo.mkdir(parents=True);build=repo/'hello.build';build.write_text('pkgname=hello\npkgver=1\nslot=0\ndepends=()\nsource=()\n')
        configs=self.etc/'repos.conf.d';configs.mkdir();(configs/'local.conf').write_text('type=local\npath='+str(self.root/'repo')+'\n')
        (self.etc/'world').write_text('');cache=self.root/'var/cache/corix/binaries';cache.mkdir(parents=True,exist_ok=True)
        binary=cache/f'dev_hello-1-0-{platform.machine()}.corix.tar.gz'
        def package(failing=False):
            with tarfile.open(binary,'w:gz') as tf:
                e=tarfile.TarInfo('usr/bin/hello');e.size=5;tf.addfile(e,io.BytesIO(b'hello'))
                if failing:
                    data=b'exit 1\n';e=tarfile.TarInfo('usr/share/corix/post-install.sh');e.size=len(data);tf.addfile(e,io.BytesIO(data))
            pathlib.Path(str(binary)+'.sig.gpg').write_bytes(signer.signature(binary.read_bytes()))
        package();self.run_core('_update_metadata_cache')
        target=self.root/'usr/bin/hello';target.parent.mkdir(parents=True);target.write_text('unowned')
        before=self.semantic();self.run_core('DEP_MODE=auto; corix_install dev/hello:0',False);self.assertEqual(target.read_text(),'unowned');self.assertEqual(self.semantic(),before)
        target.unlink();binary.write_bytes(b'corrupted')
        self.run_core('DEP_MODE=auto; corix_install dev/hello:0',False);self.assertFalse(target.exists());self.assertEqual(self.semantic(),before)
        package(True);self.run_core('DEP_MODE=auto; corix_install dev/hello:0',False);self.assertFalse(target.exists());self.assertEqual(self.semantic(),before);self.assertEqual((self.etc/'world').read_text(),'')
        package()
        # Reproduce build -> publish -> install: registration must bind the archive, not its ownership manifest.
        self.run_core('blockchain_register_package dev/hello 1 '+hashlib.sha256(binary.read_bytes()).hexdigest()+' '+hashlib.sha256(build.read_bytes()).hexdigest()+' >/dev/null; blockchain_mine_block >/dev/null')
        self.run_core('DEP_MODE=auto; corix_install dev/hello:0')
        with sqlite3.connect(self.chain) as db:
            registrations=db.execute("SELECT data FROM transactions WHERE type='package_register' AND json_extract(data,'$.version')='1'").fetchall()
            self.assertEqual(len(registrations),1);self.assertEqual(json.loads(registrations[0][0])['hash'],hashlib.sha256(binary.read_bytes()).hexdigest())
        self.assertEqual(target.read_bytes(),b'hello');self.assertIn('dev/hello:0',(self.etc/'world').read_text())
        # Upgrade must reinstall the new version, and rollback a failing new package.
        installed=self.base/'installed/dev_hello-0'
        build.write_text('pkgname=hello\npkgver=2\nslot=0\ndepends=()\nsource=()\n')
        binary=cache/f'dev_hello-2-0-{platform.machine()}.corix.tar.gz'
        package(True);expected=self.semantic()
        self.run_core('DEP_MODE=auto; corix_upgrade',False)
        self.assertEqual((installed/'version').read_text().strip(),'1');self.assertEqual(target.read_bytes(),b'hello');self.assertEqual(self.semantic(),expected)
        package();self.run_core('DEP_MODE=auto; corix_upgrade')
        self.assertEqual((installed/'version').read_text().strip(),'2');self.run_core('corix_owns /usr/bin/hello')
        self.run_core('DEP_MODE=auto; corix_upgrade') # Repeated up-to-date upgrade.
        # Cached rollback uses the real historical build metadata and the native installer.
        old_binary=cache/f'dev_hello-1-0-{platform.machine()}.corix.tar.gz';old_bytes=old_binary.read_bytes()
        build.write_text('pkgname=hello\npkgver=1\nslot=0\ndepends=()\nsource=()\n')
        before=self.semantic();old_binary.write_bytes(b'corrupted rollback archive')
        self.run_core('DEP_MODE=auto; corix_rollback dev/hello:0 1 <<< y',False)
        self.assertEqual((installed/'version').read_text().strip(),'2');self.assertEqual(target.read_bytes(),b'hello');self.assertEqual(self.semantic(),before)
        old_binary.write_bytes(old_bytes);self.run_core('DEP_MODE=auto; corix_rollback dev/hello:0 1 <<< y')
        self.assertEqual((installed/'version').read_text().strip(),'1');self.assertEqual(target.read_bytes(),b'hello')
        build.write_text('pkgname=hello\npkgver=2\nslot=0\ndepends=()\nsource=()\n')
        self.run_core('DEP_MODE=auto; corix_upgrade');self.assertEqual((installed/'version').read_text().strip(),'2')
        # A failed pre-remove hook must leave the installed package and world intact.
        hook=installed/'pre-remove.sh';hook.write_text('exit 1\n');hook.chmod(0o700)
        before=self.semantic();world=(self.etc/'world').read_text()
        self.run_core('corix_remove dev/hello:0 <<< y',False)
        self.assertEqual((installed/'version').read_text().strip(),'2');self.assertEqual(target.read_bytes(),b'hello');self.assertEqual(self.semantic(),before);self.assertEqual((self.etc/'world').read_text(),world)
        hook.unlink()
        self.run_core('corix_remove dev/hello:0 <<< y');self.assertFalse(target.exists());self.assertEqual((self.etc/'world').read_text(),'')

    def test_autoremove_preserves_installed_dependencies_and_adopt_root(self):
        repo=self.root/'repo/dev/app';repo.mkdir(parents=True);(repo/'app.build').write_text('pkgname=app\npkgver=1\ndepends=(dev/needed)\n')
        dep=self.root/'repo/dev/needed';dep.mkdir();(dep/'needed.build').write_text('pkgname=needed\npkgver=1\n')
        configs=self.etc/'repos.conf.d';configs.mkdir();(configs/'local.conf').write_text('type=local\npath='+str(self.root/'repo')+'\n')
        (self.etc/'world').write_text('dev/app:0\n')
        for name in ('app','needed','orphan'):
            directory=self.base/f'installed/dev_{name}-0';directory.mkdir(parents=True)
            (directory/'name').write_text('dev/'+name);(directory/'slot').write_text('0');(directory/'version').write_text('1');(directory/'files').write_text('usr/bin/'+name+'\n');(directory/'dependencies').write_text('')
            target=self.root/'usr/bin'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(name)
        self.run_core("_update_metadata_cache; corix_autoremove <<< $'y\ny'")
        self.assertTrue((self.root/'usr/bin/app').exists());self.assertTrue((self.root/'usr/bin/needed').exists());self.assertFalse((self.root/'usr/bin/orphan').exists())
        self.assertEqual(set(self.run_core('_installed_package_ids').stdout.splitlines()),{'dev/app:0','dev/needed:0'})
        target=self.root/'usr/bin/adopted';target.write_text('existing');manifest=self.root/'adopted.manifest';manifest.write_text('usr/bin/adopted\n')
        self.run_core('corix_adopt dev/adopted 1 <<< "$CORIUM_ROOT/adopted.manifest"')
        self.assertTrue((self.base/'installed/dev_adopted-0/files').exists());self.assertIn('dev/adopted:0',(self.etc/'world').read_text())

    def test_adopt_ownership_traversal_missing_symlink_and_eof_are_atomic(self):
        target=self.root/'usr/bin/name..valid';target.parent.mkdir(parents=True);target.write_text('owned')
        manifest=self.root/'adopt.manifest';world=self.etc/'world';world.write_text('')
        before=self.semantic()
        for path in ('../outside','/absolute','usr/bin/missing'):
            manifest.write_text(path+'\n');self.run_core('corix_adopt dev/adopted 1 <<< "$CORIUM_ROOT/adopt.manifest"',False)
            self.assertEqual(self.semantic(),before);self.assertEqual(world.read_text(),'')
        link=self.root/'linked';link.symlink_to(target.parent,target_is_directory=True)
        manifest.write_text('linked/name..valid\n');self.run_core('corix_adopt dev/adopted 1 <<< "$CORIUM_ROOT/adopt.manifest"',False)
        self.run_core('corix_adopt dev/adopted 1 < /dev/null',False)
        manifest.write_text('usr/bin/name..valid\n');self.run_core('corix_adopt dev/adopted 1 <<< "$CORIUM_ROOT/adopt.manifest"')
        after=self.semantic();self.run_core('corix_adopt dev/other 1 <<< "$CORIUM_ROOT/adopt.manifest"',False)
        self.assertEqual(self.semantic(),after);self.assertEqual(world.read_text(),'dev/adopted:0\n');self.assertEqual(target.read_text(),'owned')
    def test_p2p_repository_archive_atomic_and_traversal_rejection(self):
        repos=self.root/'usr/corix/repos/networks/default';repos.mkdir(parents=True,exist_ok=True)
        old=repos/'sample';old.mkdir();(old/'old').write_text('original')
        archive=self.root/'repo.tar.gz'
        def packed(name,data):
            with tarfile.open(archive,'w:gz') as tf:
                item=tarfile.TarInfo(name);item.size=len(data);tf.addfile(item,io.BytesIO(data))
            # Existing content-addressed object discovery publishes actual archive bytes.
            return self.run_core('_p2p_upload_file "$CORIUM_ROOT/repo.tar.gz"').stdout.splitlines()[-1]
        digest=packed('../outside',b'unsafe')
        self.run_core('p2p_sync_repository sample '+shlex.quote(digest),False)
        self.assertEqual((old/'old').read_text(),'original');self.assertFalse((repos/'outside').exists())
        digest=packed('dev/pkg/pkg.build',b'pkgname=pkg\npkgver=1\n')
        self.run_core('p2p_sync_repository sample '+shlex.quote(digest))
        self.assertFalse((old/'old').exists());self.assertEqual((old/'dev/pkg/pkg.build').read_text(),'pkgname=pkg\npkgver=1\n')
    def test_unknown_transaction_noninteractive_fails_closed(self):
        self.run_core("_handle_dynamic_application_transaction unrecognized '{}' "+('a'*64)+' '+self.identity+' 1 < /dev/null',False)

    def test_state_correction_sql_types_atomicity_and_unicode(self):
        with sqlite3.connect(self.chain) as db:
            db.execute('INSERT INTO contribution_scores(user_id,score,last_update_height) VALUES (?,10,0)',(self.identity,))
        correction=[{'operation':'CREDIT','table':'contribution_scores','user_id':self.identity,'amount':7}]
        self.run_core('_execute_state_correction '+shlex.quote(json.dumps(correction)))
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT score FROM contribution_scores').fetchone()[0],17)
        for item in [dict(correction[0],table='contribution_scores; DROP TABLE validators;--'),dict(correction[0],amount=True),dict(correction[0],amount=2**63),{'operation':'UPDATE','table':'problem_sets','set_id':'x','update_fields':{'name=1;--':'x'}},{'operation':'INVALIDATE_TX','tx_hash':'bad','height':1}]:
            before=self.semantic();self.run_core('_execute_state_correction '+shlex.quote(json.dumps(correction+[item])),False);self.assertEqual(self.semantic(),before)
        veto={'operation':'INVALIDATE_TX','tx_hash':'a'*64,'height':7,'reason':"中文|🙂\nquote'"}
        self.run_core('_execute_state_correction '+shlex.quote(json.dumps([veto],ensure_ascii=False)))
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT reason,invalidation_height FROM invalidated_transactions').fetchone(),(veto['reason'],7))
    def test_state_correction_signed_batch_incremental_replay_and_phoenix_authority(self):
        from test_pgp_fixture import OpenPGPFixture
        signer=OpenPGPFixture();authority=signer.armor(signer.keyring(),'PUBLIC KEY BLOCK')
        with sqlite3.connect(self.chain) as db:db.execute("INSERT INTO chain_state VALUES ('core_gpg_authority',?)",(authority,))
        # A signed Phoenix anchor supplies the initial score, so every value is replayable.
        anchor=self.snapshot('initial-authority.json')
        anchor['state']['chain_tables']['contribution_scores']=[{'user_id':self.identity,'score':10,'last_update_height':0}]
        del anchor['state_root'];del anchor['snapshot_signature']
        anchor_root=hashlib.sha256(json.dumps(anchor,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        anchor.update(state_root=anchor_root,snapshot_signature=self.sign(anchor_root))
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM blocks')
        self.import_snapshot(anchor);(self.etc/'genesis.json').write_text(json.dumps(anchor))
        transitions=[{'operation':'CREDIT','table':'contribution_scores','user_id':self.identity,'amount':7},{'operation':'INVALIDATE_TX','tx_hash':'a'*64,'reason':"中文|🙂\nquote'"}]
        canonical=json.dumps(transitions,ensure_ascii=False,separators=(',',':'))
        payload={'state_transitions':transitions,'authority_signature':signer.armor(signer.signature(canonical.encode()),'SIGNATURE')}
        timestamp=1;body=json.dumps({'type':'state_correction_tx','data':payload,'timestamp':timestamp},ensure_ascii=False,separators=(',',':'))
        digest=hashlib.sha256(body.encode()).hexdigest()
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,NULL)',(digest,'state_correction_tx',json.dumps(payload,ensure_ascii=False,separators=(',',':')),self.sign(body),self.pem,timestamp))
        self.run_core('declare -A tracker=() cache=(); _validate_single_transaction '+digest+' "" "" 1 tracker cache')
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],1,'Validation emitted a transaction')
        with sqlite3.connect(self.chain) as db:
            previous=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
            body=json.dumps({'height':1,'previous_hash':previous,'timestamp':2,'transactions':[digest]},separators=(',',':'));bh=hashlib.sha256(body.encode()).hexdigest()
            db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)',(1,bh,previous,2,self.identity,self.sign(body),json.dumps([digest]),1000));db.execute('UPDATE transactions SET block_height=1 WHERE hash=?',(digest,))
        self.add_empty_block(2);self.run_core('_update_chain_state_cache')
        state=self.semantic();self.assertEqual(state['chain']['invalidated_transactions'][0]['reason'],transitions[1]['reason']);self.assertEqual(state['chain']['contribution_scores'][0]['score'],17)
        self.assertEqual(state['chain']['invalidated_transactions'][0]['invalidation_height'],1)
        self.run_core('_internal_rebuild_derived_state');self.assertEqual(self.semantic(),state)
        snapshot=self.snapshot('correction.json',2);self.assertEqual(snapshot['state']['chain_tables']['chain_state'],[{'key':'core_gpg_authority','value':authority}])
        with sqlite3.connect(self.chain) as db:db.execute('DELETE FROM blocks');db.execute("DELETE FROM chain_state WHERE key='core_gpg_authority'")
        self.import_snapshot(snapshot)
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute("SELECT value FROM chain_state WHERE key='core_gpg_authority'").fetchone()[0],authority)
        (self.etc/'genesis.json').write_text(json.dumps(snapshot));again=self.snapshot('correction-again.json')
        self.assertEqual(again['state'],snapshot['state'])

    def test_peer_address_ipv6_legacy_and_invalid_parsing(self):
        node=self.identity
        for address,host,port in [(node+':ipv6:2001:db8::1:31337','2001:db8::1','31337'),(node+':ipv6:[::1]:31337','::1','31337'),(node+':ipv4:127.0.0.1:31337','127.0.0.1','31337'),(node+':127.0.0.1:31337','127.0.0.1','31337')]:
            output=self.run_core('_parse_full_address '+shlex.quote(address)+"; printf '%s|%s\\n' \"$ADDR_HOST\" \"$ADDR_PORT\"").stdout.strip()
            self.assertEqual(output,host+'|'+port)
        for address in ('bad:ipv4:127.0.0.1:1',node+':ipv4:127.0.0.1:99999',node+':unsupported:localhost:1'):
            self.run_core('_parse_full_address '+shlex.quote(address),False)

    def test_package_registration_duplicate_conflict_and_corruption(self):
        first=self.run_core('blockchain_register_package dev/pkg 1 '+('a'*64)+' '+('b'*64)).stdout.splitlines()[-1]
        repeat=self.run_core('blockchain_register_package dev/pkg 1 '+('a'*64)+' '+('b'*64)).stdout.splitlines()[-1]
        self.assertEqual(first,repeat)
        with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],1)
        self.run_core('blockchain_register_package dev/pkg 1 '+('c'*64)+' '+('b'*64),False)
        with sqlite3.connect(self.chain) as db:db.execute("UPDATE transactions SET signature='00'")
        self.run_core('blockchain_register_package dev/pkg 1 '+('a'*64)+' '+('b'*64),False)

if __name__=='__main__':unittest.main(verbosity=2)
