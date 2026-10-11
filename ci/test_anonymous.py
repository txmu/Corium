"""Actual Tor onion/I2P destinations, production TLS transport and pin rejection."""
import base64
import hashlib
import json
import os
import pathlib
import shlex
import signal
import subprocess
import time
from test_core import Fixture
from test_gateway import SOURCE

class AnonymousNetworks(Fixture):
    def stop(self,process):
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=20)
            except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL); process.wait()

    def start(self,command,logname):
        stream=pathlib.Path('ci-logs',logname).open('w'); self.addCleanup(stream.close)
        proc=subprocess.Popen(command,stdout=stream,stderr=stream,start_new_session=True)
        self.addCleanup(self.stop,proc); return proc

    def test_real_anonymous_destination_ping_and_wrong_tls_pin_rejection(self):
        backend=os.environ['CORIUM_ANONYMOUS_BACKEND']
        ready=self.root/'remote.json'
        peer=self.start(['python3','ci/network_peer.py','--host','127.0.0.1','--ready',str(ready)],'anonymous-peer.log')
        deadline=time.monotonic()+30
        while time.monotonic()<deadline and not ready.exists() and peer.poll() is None: time.sleep(.1)
        self.assertTrue(ready.exists(),'Real TLS peer did not start')
        remote=json.loads(ready.read_text())
        if backend=='tor':
            data=self.root/'tor'; data.mkdir(mode=0o700)
            config=self.root/'torrc'
            config.write_text('DataDirectory '+str(data)+'\nSocksPort 127.0.0.1:19050\nHiddenServiceDir '+str(data/'onion')+'\nHiddenServicePort 443 127.0.0.1:19345\nLog notice stdout\n')
            process=self.start(['tor','-f',str(config)],'tor.log')
            deadline=time.monotonic()+600; hostname=data/'onion/hostname'
            while time.monotonic()<deadline and process.poll() is None:
                if hostname.exists() and 'Bootstrapped 100%' in pathlib.Path('ci-logs/tor.log').read_text(): break
                time.sleep(2)
            self.assertTrue(hostname.exists(),'Tor onion service failed to publish')
            self.assertIn('Bootstrapped 100%',pathlib.Path('ci-logs/tor.log').read_text())
            address=hostname.read_text().strip(); address_type='onion_v3'; proxy='socks5h://127.0.0.1:19050'; cache_key='p2p_tor_proxy'
        elif backend=='i2p':
            data=self.root/'i2pd'; data.mkdir()
            config=self.root/'i2pd.conf'; tunnels=self.root/'tunnels.conf'
            config.write_text('daemon=false\nlog=stdout\nloglevel=debug\n[http]\nenabled=true\nport=17070\n[httpproxy]\nenabled=true\nport=14444\n[socksproxy]\nenabled=true\nport=14447\n')
            tunnels.write_text('[corium-ci]\ntype=server\nhost=127.0.0.1\nport=19345\ninport=443\nkeys=corium-ci.dat\ninbound.length=2\noutbound.length=2\n')
            process=self.start(['i2pd','--service=false','--datadir='+str(data),'--conf='+str(config),'--tunconf='+str(tunnels)],'i2p.log')
            deadline=time.monotonic()+600; keys=data/'corium-ci.dat'
            while time.monotonic()<deadline and not keys.exists() and process.poll() is None: time.sleep(2)
            self.assertTrue(keys.exists(),'I2P destination keys were not generated')
            raw=keys.read_bytes(); self.assertGreaterEqual(len(raw),387)
            destination=raw[:387+int.from_bytes(raw[385:387],'big')]
            address=base64.b32encode(hashlib.sha256(destination).digest()).decode().rstrip('=').lower()+'.b32.i2p'
            address_type='i2p_b32'; proxy='http://127.0.0.1:14444'; cache_key='p2p_i2p_proxy'
        else: raise AssertionError('Unknown backend '+backend)
        self.run_core('dht_add_node '+remote['id']+' '+address_type+' '+address+' 443')
        cache=self.root/'var/lib/corix/p2p/peer_certs'; cache.mkdir(parents=True,exist_ok=True)
        pinned=cache/(address+'_443.pem'); pinned.write_bytes(pathlib.Path(remote['cert']).read_bytes())
        command='CORIUM_CONFIG_CACHE['+cache_key+']='+shlex.quote(proxy)+'; _dht_send_message_direct '+remote['id']+' PING anonymous-ci'
        deadline=time.monotonic()+600; success=False; trace=[]
        while time.monotonic()<deadline:
            # Public networks may need time to publish descriptors and establish tunnels.
            result=subprocess.run(['bash','-c','source '+shlex.quote(str(SOURCE))+'\n'+command],env=self.env,capture_output=True,text=True,timeout=90)
            trace.append(result.stdout+result.stderr)
            if result.returncode==0 and 'PONG' in result.stdout: success=True; break
            time.sleep(5)
        pathlib.Path('ci-logs/anonymous-transport.log').write_text('\n'.join(trace))
        self.assertTrue(success,'Production transport did not reach its actual '+backend+' destination; see transport and router logs')
        # Use a different real certificate to prove the persisted pin is enforced.
        key=self.root/'wrong.key'; cert=self.root/'wrong.pem'
        self.run_core('openssl req -x509 -newkey rsa:2048 -nodes -keyout '+str(key)+' -out '+str(cert)+' -subj /CN=wrong-pin -days 1')
        pinned.write_bytes(cert.read_bytes()); expected=pinned.read_bytes()
        self.run_core(command,ok=False); self.assertEqual(pinned.read_bytes(),expected)
