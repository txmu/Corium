"""Guest-side real Corium transaction checkpoint and cold restart assertions."""
import argparse
import json
import os
import pathlib
import shlex
import sqlite3
import subprocess
import time
from test_core import Fixture
from test_gateway import SOURCE

parser=argparse.ArgumentParser(); parser.add_argument('phase',choices=['prepare','check']); parser.add_argument('--mode',choices=['uncommitted','committed'],default='uncommitted'); args=parser.parse_args()
store=pathlib.Path('/var/lib/corium-power'); store.mkdir(parents=True,exist_ok=True)
record=store/'baseline.json'; marker=store/'ready'
if args.phase=='prepare':
    os.environ['TMPDIR']=str(store)
    fixture=Fixture(); fixture.setUp()
    target=fixture.root/'usr/bin/power-tool'; target.parent.mkdir(parents=True); target.write_text('original\n')
    (fixture.etc/'world').write_text('dev/power-tool:0\n')
    (fixture.root/'manifest').write_text('usr/bin/power-tool\n')
    expected=fixture.semantic()
    checkpoint=fixture.root/'checkpoint'
    script=('source '+shlex.quote(str(SOURCE))+'\n_begin_transaction "$INSTALLED_DB"; _transaction_stage_files "$CORIUM_ROOT/manifest"; '
            'printf changed > "$CORIUM_ROOT/usr/bin/power-tool"; printf changed > "$WORLD_FILE"; '
            'db_execute_safe "$BLOCKCHAIN_DB" "UPDATE system_params SET param_value=%s WHERE param_key=%s;" 123 ci_power; ')
    # Add a genuine preexisting parameter so the transaction has a measurable database mutation.
    fixture.run_core('db_execute_safe "$BLOCKCHAIN_DB" "INSERT INTO system_params VALUES (%s,%s);" ci_power 0')
    expected=fixture.semantic()
    if args.mode=='committed': script+='_commit_transaction; '
    script+='sync; touch "$CORIUM_ROOT/checkpoint"; sleep 300'
    log=(store/'transaction.log').open('w')
    process=subprocess.Popen(['bash','-c',script],env=fixture.env,stdout=log,stderr=log,start_new_session=True)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline and not checkpoint.exists() and process.poll() is None: time.sleep(.1)
    assert checkpoint.exists(),'Production transaction failed before crash checkpoint: '+(store/'transaction.log').read_text()
    if args.mode=='committed': expected=fixture.semantic()
    record.write_text(json.dumps({'root':str(fixture.root),'semantic':expected,'mode':args.mode,'paths':[str(p) for p in (fixture.chain,fixture.forum,fixture.dht)]}))
    subprocess.run(['sync'],check=True); marker.write_text(args.mode); subprocess.run(['sync'],check=True)
    # The host kills the entire QEMU machine while the transaction processes remain alive.
    process.wait(timeout=310)
else:
    saved=json.loads(record.read_text()); root=pathlib.Path(saved['root'])
    env=dict(os.environ,CORIUM_ROOT=str(root),CORIUM_NETWORK_ID_OVERRIDE='default',CORIUM_TEST_NO_DAEMONS='1')
    result=subprocess.run(['bash','-c','source '+shlex.quote(str(SOURCE))+'\n_update_chain_state_cache; _internal_semantic_state'],env=env,capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    actual=json.loads(result.stdout.splitlines()[-1]); assert actual==saved['semantic'],'Cold reboot changed typed semantic state'
    content=(root/'usr/bin/power-tool').read_text()
    world=(root/'etc/corix/networks/default/world').read_text()
    if saved['mode']=='committed':
        assert content=='changed' and world=='changed','Committed filesystem state was lost after power cut'
    else:
        assert content=='original\n' and world=='dev/power-tool:0\n','Uncommitted filesystem state survived cold restart'
    for path in saved['paths']:
        with sqlite3.connect(path) as db: assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok',path
    print('PASS: actual QEMU cold power cut, mode='+saved['mode']+', files/world/three databases checked')
