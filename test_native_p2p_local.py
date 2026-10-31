"""Bounded local native TLS/signature/STORE/announcement experiment.

Runs the production handler in three independent processes with known loopback
addresses and pinned test certificates. It does not prove public discovery,
different operators, or acceptance/replay of a new consensus branch.
"""
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from test_gateway import SOURCE


class NativeLocalP2PTests(unittest.TestCase):
    def stop(self, process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

    def core(self, peer, command, ok=True):
        env=dict(os.environ,CORIUM_ROOT=peer['root'],CORIUM_NETWORK_ID_OVERRIDE='default',CORIUM_TEST_NO_DAEMONS='1')
        prefix='source '+shlex.quote(str(SOURCE))+'\nCORIUM_LOG_LEVEL=4\nP2P_PORT='+str(peer['port'])+'\n'
        result=subprocess.run(['bash','-c',prefix+command],env=env,capture_output=True,text=True,timeout=45)
        if ok:
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode,0,'Unreachable operation reported delivery')
        return result

    def test_native_delivery_and_survivor_peer_without_founder(self):
        with tempfile.TemporaryDirectory(prefix='corium-native-peers-') as directory:
            peers=[]
            processes=[]
            try:
                for index in range(3):
                    ready=Path(directory)/f'{index}.json'
                    log=(Path(directory)/f'{index}.log').open('w')
                    self.addCleanup(log.close)
                    process=subprocess.Popen([sys.executable,str(SOURCE.parent/'ci/network_peer.py'),
                                              '--ready',str(ready),'--host','127.0.0.1','--port','0'],
                                             stdout=log,stderr=log,start_new_session=True)
                    processes.append(process)
                    deadline=time.monotonic()+15
                    while not ready.exists() and process.poll() is None and time.monotonic()<deadline:
                        time.sleep(.05)
                    self.assertTrue(ready.exists(),'Native peer failed to start')
                    peers.append(json.loads(ready.read_text()))
                founder,b,c=peers
                # With no peers, a stored object has not been propagated.
                self.core(founder,'dht_announce_chunk '+'a'*64,ok=False)
                self.core(founder,'dht_add_node '+founder['id']+' ipv4 127.0.0.1 '+str(founder['port']))
                result=self.core(founder,'dht_announce_chunk '+'a'*64,ok=False)
                self.assertNotIn('bad array subscript',result.stderr)
                result=self.core(founder,'_internal_sync_fetch_new_blocks_to_stage "$CORIUM_ROOT/stage.db" 0',ok=False)
                self.assertIn('synchronization is unverified',result.stderr)
                for source in peers:
                    # Ensure the local TLS cert exists so _corium_address_claim
                    # does not fail with 'public certificate budget'.
                    tls_dir=Path(source['root'])/'etc/corix/networks/default'
                    tls_dir.mkdir(parents=True,exist_ok=True)
                    tls_cert=tls_dir/'tls.crt'
                    if not tls_cert.exists():
                        tls_cert.write_bytes(Path(source['cert']).read_bytes())
                    for target in peers:
                        if source is target:
                            continue
                        self.core(source,'dht_add_node '+target['id']+' ipv4 127.0.0.1 '+str(target['port']))
                        cache=Path(source['root'])/'var/lib/corix/p2p/peer_certs'
                        cache.mkdir(parents=True,exist_ok=True)
                        (cache/f"127.0.0.1_{target['port']}.pem").write_bytes(Path(target['cert']).read_bytes())
                self.assertIn('PONG',self.core(founder,'dht_send_message '+b['id']+' PING local-native').stdout)
                self.core(founder,'dht_announce_chunk '+'a'*64)
                for peer in (b,c):
                    with sqlite3.connect(peer['dht']) as db:
                        row=db.execute('SELECT nodes FROM chunks WHERE hash=?',('a'*64,)).fetchone()
                        self.assertIsNotNone(row)
                        self.assertIn(founder['id'],row[0])
                with sqlite3.connect(founder['chain']) as db:
                    genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()[0]
                self.core(founder,'_blockchain_broadcast_new_block '+genesis)
                self.stop(processes[0])
                self.assertIsNotNone(processes[0].poll())
                for peer in (b,c):
                    with sqlite3.connect(peer['dht']) as db:
                        db.execute('DELETE FROM nodes WHERE id=?',(founder['id'],))
                self.assertIn('PONG',self.core(b,'dht_send_message '+c['id']+' PING founder-stopped').stdout)
                self.core(b,'dht_announce_chunk '+'b'*64)
                with sqlite3.connect(c['dht']) as db:
                    row=db.execute('SELECT nodes FROM chunks WHERE hash=?',('b'*64,)).fetchone()
                    self.assertIsNotNone(row)
                    self.assertIn(b['id'],row[0])
            finally:
                for process in processes:
                    self.stop(process)


if __name__=='__main__':
    unittest.main()


class ExplicitSeedConfigurationTests(unittest.TestCase):
    def test_node_exclusion_blocks_before_opening_a_transport(self):
        identity='a'*64
        command='source "$1"\nCORIUM_EXCLUDED_NODES="$2"\ndht_send_message "$2" PING excluded\n'
        result=subprocess.run(['bash','-c',command,'exclude-test',str(SOURCE),identity],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,3)

    def test_host_ipv4_ipv6_and_empty_seeds_reach_native_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'etc/corix/networks/default/corix.conf';config.parent.mkdir(parents=True)
            for seeds,expected in [('', ''),('192.0.2.1:7234','ipv4:192.0.2.1:7234'),('[2001:db8::1]:7234','ipv6:[2001:db8::1]:7234'),('seed.example:7234','dns:seed.example:7234')]:
                config.write_text('[p2p]\nseed_peers='+seeds+'\n');config.chmod(0o600)
                result=subprocess.run(['bash','-c','source "$1"\nload_config || exit 2\nprintf "%s" "$DHT_BOOTSTRAP_NODES_STRING"','seed-test',str(SOURCE)],env=dict(os.environ,CORIUM_ROOT=str(root)),capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,expected)
            config.write_text('[p2p]\nseed_peers=bad/path:7234\n');config.chmod(0o600)
            result=subprocess.run(['bash','-c','source "$1"\nload_config','seed-test',str(SOURCE)],env=dict(os.environ,CORIUM_ROOT=str(root)),capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
