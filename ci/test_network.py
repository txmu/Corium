"""Three independent HTTPS peers across routed/SNAT Linux namespaces + real STUN."""
import ast
import json
import os
import pathlib
import shlex
import signal
import socket
import sqlite3
import subprocess
import time
import unittest
from test_gateway import SOURCE,DAEMON

class Network(unittest.TestCase):
    def setUp(self):
        self.peers={}; self.logs={}
        for name,ns,ip in [('a','corium-a','10.81.1.2'),('b','corium-b','10.81.2.2'),('relay','corium-wan','198.18.0.2')]:
            ready=pathlib.Path(os.environ['RUNNER_TEMP'])/(name+'-peer.json'); ready.unlink(missing_ok=True)
            log=pathlib.Path('ci-logs')/(name+'-peer.log'); stream=log.open('w'); self.addCleanup(stream.close)
            proc=subprocess.Popen(['ip','netns','exec',ns,'env','PATH='+os.environ['PATH'],'PYTHONPATH='+str(SOURCE.parent),'python3','ci/network_peer.py','--ready',str(ready)],stdout=stream,stderr=stream,start_new_session=True)
            self.addCleanup(self.stop,proc)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline and not ready.exists() and proc.poll() is None: time.sleep(.1)
            self.assertTrue(ready.exists(),'Peer failed to start: '+log.read_text())
            data=json.loads(ready.read_text()); data.update(namespace=ns,ip=ip); self.peers[name]=data; self.logs[name]=log
        for source in self.peers.values():
            for target in self.peers.values():
                self.core(source, 'dht_add_node '+target['id']+' ipv4 '+target['ip']+' '+str(target['port']))
                cache=pathlib.Path(source['root'])/'var/lib/corix/p2p/peer_certs'; cache.mkdir(parents=True,exist_ok=True)
                (cache/(target['ip']+'_'+str(target['port'])+'.pem')).write_bytes(pathlib.Path(target['cert']).read_bytes())
        self.router('iptables -F FORWARD')

    def stop(self,proc):
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); proc.wait()

    def core(self,peer,script,ok=True):
        env=dict(os.environ,CORIUM_ROOT=peer['root'],CORIUM_NETWORK_ID_OVERRIDE='default',CORIUM_TEST_NO_DAEMONS='1')
        command=['ip','netns','exec',peer['namespace'],'bash','-c','source '+shlex.quote(str(SOURCE))+'\n'+script]
        result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=120)
        if ok and result.returncode: self.fail(script+'\n'+result.stdout+result.stderr)
        if not ok and not result.returncode: self.fail('Unreachable operation reported success: '+script)
        return result

    def router(self,command):
        subprocess.run(['ip','netns','exec','corium-router','bash','-c',command],check=True)

    def test_real_stun_through_snat_and_production_public_address_discovery(self):
        stream=pathlib.Path('ci-logs/stun-server.log').open('w'); self.addCleanup(stream.close)
        proc=subprocess.Popen(['ip','netns','exec','corium-wan','turnserver','-n','--no-cli','--no-auth','--stun-only','--listening-ip=198.18.0.2','--listening-port=3478','--alt-listening-port=3479','--log-file=stdout'],stdout=stream,stderr=stream,start_new_session=True)
        self.addCleanup(self.stop,proc); time.sleep(2); self.assertIsNone(proc.poll())
        output=self.core(self.peers['a'],"CORIUM_STUN_SERVERS=198.18.0.2:3478 python3 -c "+shlex.quote(
            "import ast,os,json; from test_gateway import DAEMON; os.environ['SCRIPT_PATH']="+repr(str(SOURCE))+"; ns={'__name__':'stun_ci','PUBLIC_IP':None,'PUBLIC_PORT':None,'NAT_TYPE':None}; nodes=ast.parse(DAEMON).body; boundary=next(i for i,n in enumerate(nodes) if isinstance(n,ast.ClassDef) and n.name=='SandboxAPI'); exec(compile(ast.Module(body=nodes[:boundary],type_ignores=[]),'gateway','exec'),ns); ns['discover_public_address'](); print(json.dumps({'ip':ns['PUBLIC_IP'],'port':ns['PUBLIC_PORT']}))")).stdout
        data=json.loads(output.splitlines()[-1]); self.assertEqual(data['ip'],'198.18.0.1'); self.assertGreater(data['port'],0)
        counters=subprocess.check_output(['ip','netns','exec','corium-router','iptables','-t','nat','-L','POSTROUTING','-n','-v'],text=True)
        self.assertIn('MASQUERADE',counters); pathlib.Path('ci-logs/nat-counters.txt').write_text(counters)

    def test_real_multipeer_direct_tls_and_signed_store(self):
        a,b=self.peers['a'],self.peers['b']
        self.assertIn('PONG',self.core(a,'dht_send_message '+b['id']+' PING native-network').stdout)
        self.core(a,'dht_send_message '+b['id']+' STORE '+shlex.quote('a'*64+' '+a['id']))
        with sqlite3.connect(b['dht']) as db:
            row=db.execute('SELECT nodes FROM chunks WHERE hash=?',('a'*64,)).fetchone()
        self.assertIsNotNone(row); self.assertIn(a['id'],row[0])

    def test_firewall_blocks_direct_then_real_relay_reaches_target(self):
        a,b,relay=self.peers['a'],self.peers['b'],self.peers['relay']
        self.router('iptables -A FORWARD -i lan-a -o lan-b -p tcp -j REJECT')
        self.core(a,'_dht_send_message_direct '+b['id']+' PING direct-blocked',ok=False)
        command='P2P_RELAY_NODES=('+relay['id']+'); CORIUM_CONFIG_CACHE[p2p_enable_hole_punching]=false; dht_send_message '+b['id']+' PING relay-ci'
        self.assertIn('PONG',self.core(a,command).stdout)
        self.assertIn('RELAY_MESSAGE',self.logs['relay'].read_text())
        self.assertIn('PING',self.logs['b'].read_text())

    def test_hole_punch_signal_relay_actual_reverse_connection(self):
        a,b,relay=self.peers['a'],self.peers['b'],self.peers['relay']
        self.router('iptables -A FORWARD -i lan-a -o lan-b -p tcp -m conntrack --ctstate NEW -j REJECT')
        payload=b['id']+'|'+a['id']+'|'+a['id']+':ipv4:'+a['ip']+':'+str(a['port'])
        self.core(a,'dht_send_message '+relay['id']+' PUNCH_HOLE_SIGNAL '+shlex.quote(payload))
        deadline=time.monotonic()+40
        while time.monotonic()<deadline and 'type=PING' not in self.logs['a'].read_text(): time.sleep(.2)
        self.assertIn('PUNCH_HOLE_EXECUTE',self.logs['b'].read_text())
        # PING handling logs the type but not arbitrary payload, inspect the actual response path too.
        self.assertIn('type=PING',self.logs['a'].read_text(),'No reverse network connection reached the requester')

    def test_real_upnp_igd_discovery_and_all_three_production_port_mappings(self):
        # This WAN alias exists only inside the isolated router namespace.
        # miniupnpd rejects RFC 2544 benchmark addresses as advertised external IPs.
        self.router('ip addr add 11.81.3.1/32 dev wan0')
        self.addCleanup(self.router,'ip addr del 11.81.3.1/32 dev wan0')
        config=pathlib.Path(os.environ['RUNNER_TEMP'])/'miniupnpd.conf'
        config.write_text('ext_ifname=wan0\next_ip=11.81.3.1\nlistening_ip=10.81.1.1\nenable_upnp=yes\nenable_natpmp=yes\nsecure_mode=yes\nsystem_uptime=yes\nuuid=12345678-1234-1234-1234-123456789abc\nallow 1024-65535 10.81.1.0/24 1024-65535\n')
        # miniupnpd needs its chains in this router namespace, independently of the host service.
        self.router('set -e\niptables -N MINIUPNPD\niptables -A FORWARD -j MINIUPNPD\n'
                    'iptables -t nat -N MINIUPNPD\niptables -t nat -A PREROUTING -j MINIUPNPD\n'
                    'iptables -t nat -N MINIUPNPD-POSTROUTING\niptables -t nat -A POSTROUTING -j MINIUPNPD-POSTROUTING')
        stream=pathlib.Path('ci-logs/upnp-router.log').open('w'); self.addCleanup(stream.close)
        proc=subprocess.Popen(['ip','netns','exec','corium-router','miniupnpd','-d','-f',str(config)],stdout=stream,stderr=stream,start_new_session=True)
        self.addCleanup(self.stop,proc); time.sleep(2); self.assertIsNone(proc.poll())
        code=("import ast,os,json,miniupnpc; from test_gateway import DAEMON; os.environ.update(SCRIPT_PATH="+repr(str(SOURCE))+
              ",CORIUM_ENABLE_UPNP='true',CORIUM_P2P_PORT='18345',CORIUM_P2P_HTTP_PORT_OFFSET='1000',CORIUM_P2P_FILE_PORT_OFFSET='2000'); "
              "ns={'__name__':'upnp_ci'}; nodes=ast.parse(DAEMON).body; boundary=next(i for i,n in enumerate(nodes) if isinstance(n,ast.ClassDef) and n.name=='SandboxAPI'); "
              "exec(compile(ast.Module(body=nodes[:boundary],type_ignores=[]),'gateway','exec'),ns); ns['setup_automatic_port_forwarding'](); "
              "u=miniupnpc.UPnP(); u.discoverdelay=2000; u.discover(); u.selectigd(); print(json.dumps([u.getspecificportmapping(p,'TCP') for p in (18345,19345,20345)]))")
        output=self.core(self.peers['a'],'python3 -c '+shlex.quote(code)).stdout
        mappings=json.loads(output.splitlines()[-1]); self.assertEqual(len(mappings),3)
        for mapping in mappings:
            self.assertIsNotNone(mapping); self.assertEqual(mapping[0],'10.81.1.2')
