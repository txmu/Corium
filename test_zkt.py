"""Test native Corium ZKT reputation points integration.

ZKT is non-monetary reputation/merit credits, not a financial token or cryptocurrency.
Tests verify status, account queries, and service contribution claims.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parent / "corix_v108.sh"


class CoriumZKTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="corium-zkt-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "state"
        self.env = {**os.environ, "CORIUM_ROOT": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}
        self.operator = "f" * 64

    def invoke(self, *args, data=None):
        return subprocess.run(["bash", str(SCRIPT), *args], input=data,
                              capture_output=True, text=True, env=self.env, timeout=15)

    def test_corix_zkt_status_and_account_via_cli(self):
        # 1. Query status on fresh chain
        res = self.invoke("zkt", "status")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertFalse(data["is_financial_token"])
        self.assertEqual(data["reputation_type"], "merit_and_service_credit")
        self.assertEqual(data["total_reputation_awarded"], 0)
        self.assertIn("Core-Rust", data["urgent_cores"])
        self.assertIn("wiki", data["application_services"])

        # 2. Query account on fresh chain
        res = self.invoke("zkt", "account", self.operator)
        self.assertEqual(res.returncode, 0, res.stderr)
        acct = json.loads(res.stdout)
        self.assertEqual(acct["total_reputation"], 0)
        self.assertEqual(acct["tier"], "Contributor")

        # 3. Record a service contribution claim
        claim = {
            "schema": "ziokt.zkt-service-claim.v1",
            "operator": self.operator,
            "provider": "corium",
            "service_kind": "application",
            "service_name": "wiki",
            "units_delivered": 4,
            "evidence_digest": "sha256:" + hashlib.sha256(b"wiki-proof").hexdigest(),
            "epoch": 1,
            "nonce": "test-nonce-1",
        }
        res = self.invoke("zkt", "record", json.dumps(claim))
        self.assertEqual(res.returncode, 0, res.stderr)
        awarded = json.loads(res.stdout)
        self.assertEqual(awarded["status"], "awarded")
        self.assertEqual(awarded["points_awarded"], 60)  # 15 * 4
        self.assertEqual(awarded["total_reputation"], 60)

        # 4. Verify account now reflects points
        res = self.invoke("zkt", "account", self.operator)
        self.assertEqual(res.returncode, 0, res.stderr)
        acct = json.loads(res.stdout)
        self.assertEqual(acct["total_reputation"], 60)
        self.assertEqual(acct["corium_app_reputation"], 60)
        self.assertEqual(acct["shadow6_core_reputation"], 0)
        self.assertEqual(acct["claims_count"], 1)

    def test_native_signed_governance_cli_and_duplicate_evidence(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        keys=[Ed25519PrivateKey.generate() for _ in range(2)]
        pub=[k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex() for k in keys]
        policy=json.loads(self.invoke('zkt','status').stdout)['policy']
        policy['governance']={'authorities':dict(zip(pub,['one','two'])),'threshold':2,'minimum_domains':2,'veto_threshold':2,'timelock_seconds':60,'voting_period_seconds':3600}
        self.assertEqual(self.invoke('zkt','policy',json.dumps(policy)).returncode,0)
        nxt=json.loads(json.dumps(policy));nxt['version']+=1
        def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        def signed(value,i):
            domain='Ziokt/zkt-governance/v1'
            return json.dumps({'schema':'ziokt.signed.v1','domain':domain,'public_key':pub[i],'payload':value,'signature':keys[i].sign((domain+'\n').encode()+encode(value)).hex()})
        now=int(time.time());doc={'operation':'propose','network_id':policy['network_id'],'base_policy':hashlib.sha256(encode(policy)).hexdigest(),'policy':nxt,'nonce':'1'*64,'created_at':now,'activate_at':now+60,'expires_at':now+600}
        result=self.invoke('zkt','propose',signed(doc,0));self.assertEqual(result.returncode,0,result.stderr);pid=json.loads(result.stdout)['proposal']
        for i in range(2):
            ballot=signed({'operation':'vote','network_id':policy['network_id'],'proposal':pid,'approve':True},i)
            result=self.invoke('zkt','vote',ballot);self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotEqual(self.invoke('zkt','vote',ballot).returncode,0)
        self.assertNotEqual(self.invoke('zkt','enact',json.dumps({'proposal':pid})).returncode,0)
        self.assertNotEqual(self.invoke('zkt','policy',json.dumps(nxt)).returncode,0)
        status=json.loads(self.invoke('zkt','proposals','{}').stdout);self.assertEqual(status['proposals'][0]['id'],pid)

    def test_corix_zkt_via_federation_rpc(self):
        # Enable federation
        config = self.root / "etc/corix/networks/default/corix.conf"
        config.parent.mkdir(parents=True)
        config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=c108\nallow_mutations=FALSE\n")
        config.chmod(0o600)

        # Request zkt.status via ZFCP/1 stdio RPC
        req_status = {
            "protocol": "zfcp/1", "request_id": "req-zkt-status", "federation_id": "test",
            "provider_id": "c108", "method": "zkt.status", "params": {},
            "deadline_ms": time.time_ns() // 1_000_000 + 20_000, "nonce": "c" * 32
        }
        res = self.invoke("ziokt", "rpc", "--stdio", data=json.dumps(req_status) + "\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        resp = json.loads(res.stdout)
        self.assertTrue(resp["ok"])
        self.assertFalse(resp["result"]["is_financial_token"])

        # Request zkt.account via ZFCP/1 stdio RPC
        req_acct = {
            "protocol": "zfcp/1", "request_id": "req-zkt-acct", "federation_id": "test",
            "provider_id": "c108", "method": "zkt.account", "params": {"address": self.operator},
            "deadline_ms": time.time_ns() // 1_000_000 + 20_000, "nonce": "d" * 32
        }
        res = self.invoke("ziokt", "rpc", "--stdio", data=json.dumps(req_acct) + "\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        resp = json.loads(res.stdout)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["result"]["address"], self.operator)
        self.assertEqual(resp["result"]["tier"], "Contributor")


if __name__ == "__main__":
    unittest.main()
