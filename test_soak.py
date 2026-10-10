#!/usr/bin/env python3
"""Seeded real mixed operations with semantic invariants and reproducible traces."""
import json,os,random,sqlite3,unittest,hashlib
import test_core
class SoakTests(test_core.CoreTests):
    # Only run this mixed lifecycle here; the full core regression runs separately.
    __unittest_skip__=False
    maxDiff=None
    def test_mixed_lifecycle(self):
        seed=int(os.environ.get('CORIUM_TEST_SEED','108'));rng=random.Random(seed)
        operations=['mine','backup','object','rollback','phoenix','package','forum','exodus']
        count=int(os.environ.get('CORIUM_SOAK_ROUNDS','8'));self.assertGreaterEqual(count,len(operations))
        sequence=operations[:];rng.shuffle(sequence)
        sequence.extend(rng.choice([op for op in operations if op!='package']) for _ in range(count-len(operations)));trace=[]
        for index,operation in enumerate(sequence):
            trace.append(operation);print('seed='+str(seed)+' trace='+json.dumps(trace),flush=True)
            with self.subTest(seed=seed,trace=trace):
                try:
                    if operation=='mine':
                        data=json.dumps({'nickname':'混沌|'+str(index)+'🙂'},ensure_ascii=False,separators=(',',':'))
                        import shlex
                        self.run_core('blockchain_create_transaction set_nickname '+shlex.quote(data)+' >/dev/null; blockchain_mine_block')
                    elif operation=='backup':
                        test_core.CoreTests.test_backup_destroy_restore_semantics_repeat_and_corruption(self)
                    elif operation=='object':
                        test_core.CoreTests.test_binary_chunks_exact_and_corruption_preserves_output(self)
                    elif operation=='rollback':
                        test_core.CoreTests.test_db_transaction_nested_rollback_and_wal(self)
                    elif operation=='package':
                        test_core.CoreTests.test_signed_package_install_conflict_corruption_postinstall_failure_and_remove(self)
                    elif operation=='forum':
                        import shlex
                        body='soak body|🙂 '+str(index)
                        self.run_core('forum_create_topic '+shlex.quote('soak|'+str(index))+' '+shlex.quote(body)+" ''; blockchain_mine_block; forum_sync")
                        with sqlite3.connect(self.forum) as db:
                            row=db.execute('SELECT content_hash FROM topics WHERE title=?',('soak|'+str(index),)).fetchone()
                        self.assertIsNotNone(row);self.assertEqual((self.base/'forum/objects'/row[0]).read_text(),body)
                    elif operation=='exodus':
                        with sqlite3.connect(self.chain) as db:height=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
                        self.run_core('corix_exodus propose-snapshot '+str(height))
                        with sqlite3.connect(self.forum) as db:proposal=db.execute('SELECT proposal_hash FROM exodus_proposals ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                        self.run_core('corix_exodus notarize '+proposal)
                        self.snapshot('soak-exodus.json',height)
                        result=self.run_core('_internal_verify_exodus_quorum '+proposal+' "$CORIUM_ROOT/soak-exodus.json"')
                        self.assertTrue(json.loads(result.stdout)['quorum'])
                    else:
                        with sqlite3.connect(self.chain) as db:height=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
                        first=self.snapshot('soak-first.json',height)
                        with sqlite3.connect(self.chain) as db:db.execute("UPDATE system_params SET param_value='poisoned'")
                        second=self.snapshot('soak-second.json',height)
                        self.assertEqual(first['state'],second['state']);self.assertEqual(first['state_root'],second['state_root'])
                        self.run_core('_internal_rebuild_derived_state')
                    state=self.semantic()
                    with sqlite3.connect(self.chain) as db:height=db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
                    recovered=self.snapshot('soak-canonical.json',height)['state']
                    self.assertEqual(recovered['application_tables'],state['application'])
                    for table,rows in recovered['chain_tables'].items():self.assertEqual(rows,state['chain'][table],table)
                    for path in (self.chain,self.forum,self.dht):
                        with sqlite3.connect(path) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok',str(path))
                except Exception:
                    print('FAILING invariant seed='+str(seed)+' operation='+operation+' trace='+json.dumps(trace),flush=True)
                    for path in (self.chain,self.forum,self.dht):
                        try:
                            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                                relevant={name:db.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall() for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
                            print('RELEVANT DB '+str(path)+' '+json.dumps(relevant,ensure_ascii=False,default=lambda v:v.hex() if isinstance(v,bytes) else repr(v)),flush=True)
                        except Exception as error:
                            print('RELEVANT DB unreadable '+str(path)+' '+repr(error),flush=True)
                    raise

# Do not inherit the individual regression cases into the soak suite.
for name in dir(test_core.CoreTests):
    if name.startswith('test_'):setattr(SoakTests,name,None)
if __name__=='__main__':unittest.main(verbosity=2)
