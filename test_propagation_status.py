"""Test suite for accurate P2P and DHT propagation status taxonomy.

Validates all 7 exact propagation statuses:
1. NO_REMOTE_PEERS (INFO)
2. NO_DHT_TARGETS (INFO)
3. BROADCAST_SUCCESS (INFO)
4. BROADCAST_PARTIAL (WARN)
5. BROADCAST_FAILED (WARN)
6. ACK_TIMEOUT (WARN)
7. PEER_REJECTED (WARN)
"""
import datetime
import os
from pathlib import Path
import shlex
import subprocess
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from test_core import Fixture
from test_gateway import SOURCE


class PropagationStatusTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.fixture.setUp()
        now=datetime.datetime.now(datetime.timezone.utc)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,self.fixture.identity)])
        cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
              .public_key(self.fixture.key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1))
              .sign(self.fixture.key,hashes.SHA256()))
        (self.fixture.etc/'tls.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    def tearDown(self):
        self.fixture.doCleanups()

    def _create_peer_cert(self, port):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f'node-{port}')])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5))
                .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        cache = self.fixture.root / 'var/lib/corix/p2p/peer_certs'
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f'127.0.0.1_{port}.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    def run_corium_bash(self, command, extra_env=None):
        env = dict(self.fixture.env)
        if extra_env:
            env.update(extra_env)
        prefix = f"source {shlex.quote(str(SOURCE))}\nCORIUM_LOG_LEVEL=4\n"
        return subprocess.run(['bash', '-c', prefix + command], env=env, capture_output=True, text=True, timeout=30)

    def test_no_remote_peers_and_no_dht_targets(self):
        # 1. dht_announce_chunk with no targets -> NO_DHT_TARGETS (INFO)
        res1 = self.run_corium_bash("dht_announce_chunk " + "a" * 64)
        self.assertIn("[PROPAGATION:NO_DHT_TARGETS]", res1.stderr)
        self.assertIn("[ INFO ]", res1.stderr)
        self.assertNotIn("[ WARN ]", res1.stderr)
        self.assertNotEqual(res1.returncode, 0)

        # 2. _blockchain_broadcast_new_block with no targets -> NO_REMOTE_PEERS (INFO)
        cmd = (
            "genesis=$(db_query_safe \"$BLOCKCHAIN_DB\" 'SELECT hash FROM blocks WHERE height = 0;')\n"
            "_blockchain_broadcast_new_block \"$genesis\"\n"
        )
        res2 = self.run_corium_bash(cmd)
        self.assertEqual(res2.returncode, 0, res2.stdout + res2.stderr)
        self.assertIn("[PROPAGATION:NO_REMOTE_PEERS]", res2.stderr)
        self.assertIn("[ INFO ]", res2.stderr)
        self.assertNotIn("[ WARN ]", res2.stderr)

    def test_broadcast_failed_unreachable_target(self):
        # Unreachable host/port (connection fails during cert fetch/handshake) -> BROADCAST_FAILED (WARN)
        dummy_node = "1" * 64
        cmd = (
            f"dht_add_node {dummy_node} ipv4 127.0.0.1 1\n"
            f"dht_announce_chunk {'a'*64}\n"
        )
        res = self.run_corium_bash(cmd)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("[PROPAGATION:BROADCAST_FAILED]", res.stderr)
        self.assertIn("[ WARN ]", res.stderr)

    def test_peer_rejected(self):
        # Peer explicitly returns an error status -> PEER_REJECTED (WARN)
        port = 9993
        self._create_peer_cert(port)
        bin_dir = self.fixture.root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        mock_curl = bin_dir / "curl"
        mock_curl.write_text("""#!/bin/bash
echo '{"status": "error", "message": "Block rejected by consensus policy"}200'
exit 0
""")
        mock_curl.chmod(0o755)

        dummy_node = "2" * 64
        cmd = (
            f"dht_add_node {dummy_node} ipv4 127.0.0.1 {port}\n"
            f"dht_announce_chunk {'a'*64}\n"
        )
        res = self.run_corium_bash(cmd, extra_env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("[PROPAGATION:PEER_REJECTED]", res.stderr)
        self.assertIn("[ WARN ]", res.stderr)

    def test_ack_timeout(self):
        # Curl times out (code 28) -> ACK_TIMEOUT (WARN)
        port = 9994
        self._create_peer_cert(port)
        bin_dir = self.fixture.root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        mock_curl = bin_dir / "curl"
        mock_curl.write_text("""#!/bin/bash
exit 28
""")
        mock_curl.chmod(0o755)

        dummy_node = "3" * 64
        cmd = (
            f"dht_add_node {dummy_node} ipv4 127.0.0.1 {port}\n"
            f"dht_announce_chunk {'a'*64}\n"
        )
        res = self.run_corium_bash(cmd, extra_env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("[PROPAGATION:ACK_TIMEOUT]", res.stderr)
        self.assertIn("[ WARN ]", res.stderr)

    def test_broadcast_partial(self):
        # One target succeeds, one times out -> BROADCAST_PARTIAL (WARN)
        port1 = 9991
        port2 = 9992
        self._create_peer_cert(port1)
        self._create_peer_cert(port2)

        bin_dir = self.fixture.root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        mock_curl = bin_dir / "curl"
        mock_curl.write_text(f"""#!/bin/bash
for arg in "$@"; do
    if [[ "$arg" == *":{port1 + 1000}/"* ]] || [[ "$arg" == *":{port1}/"* ]]; then
        echo '{{"status": "success", "data": "OK"}}200'
        exit 0
    fi
done
exit 28
""")
        mock_curl.chmod(0o755)

        node_success = "4" * 64
        node_timeout = "5" * 64
        cmd = (
            f"dht_add_node {node_success} ipv4 127.0.0.1 {port1}\n"
            f"dht_add_node {node_timeout} ipv4 127.0.0.1 {port2}\n"
            f"dht_announce_chunk {'a'*64}\n"
        )
        res = self.run_corium_bash(cmd, extra_env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("[PROPAGATION:BROADCAST_PARTIAL]", res.stderr)
        self.assertIn("[ WARN ]", res.stderr)

    def test_broadcast_success(self):
        # Target succeeds -> BROADCAST_SUCCESS (INFO)
        port = 9995
        self._create_peer_cert(port)

        bin_dir = self.fixture.root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        mock_curl = bin_dir / "curl"
        mock_curl.write_text("""#!/bin/bash
echo '{"status": "success", "data": "OK"}200'
exit 0
""")
        mock_curl.chmod(0o755)

        node_success = "6" * 64
        cmd = (
            f"dht_add_node {node_success} ipv4 127.0.0.1 {port}\n"
            f"dht_announce_chunk {'a'*64}\n"
            "genesis=$(db_query_safe \"$BLOCKCHAIN_DB\" 'SELECT hash FROM blocks WHERE height = 0;')\n"
            "_blockchain_broadcast_new_block \"$genesis\"\n"
        )
        res = self.run_corium_bash(cmd, extra_env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("[PROPAGATION:BROADCAST_SUCCESS]", res.stderr)
        self.assertIn("[ INFO ]", res.stderr)
        self.assertNotIn("[ WARN ]", res.stderr)


if __name__ == '__main__':
    unittest.main()
