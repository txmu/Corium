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
