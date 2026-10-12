"""Single-file local Ziokt machine entry, with no recovery or lock side effects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parent / "corix_v108.sh"


class ZioktTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="corium-ziokt-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "state"
        self.env = {**os.environ, "CORIUM_ROOT": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("CORIUM_NETWORK_ID_OVERRIDE", None)

    def invoke(self, *args, data=None, script=SCRIPT):
        return subprocess.run(["bash", str(script), "ziokt", *args], input=data,
                              capture_output=True, text=True, env=self.env, timeout=10)

    def enable(self, network="default"):
        config = self.root / "etc/corix/networks" / network / "corix.conf"
        config.parent.mkdir(parents=True)
        config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=c108\nallow_mutations=FALSE\n")
        config.chmod(0o600)
        return config

    def request(self, **changes):
        value = {"protocol": "zfcp/1", "request_id": "request-test", "federation_id": "test",
                 "provider_id": "c108", "method": "status.get", "params": {},
                 "deadline_ms": time.time_ns() // 1_000_000 + 20_000, "nonce": "b" * 32}
        return json.dumps({**value, **changes}) + "\n"

    def test_disabled_probe_creates_no_native_root(self):
        result = self.invoke("capabilities")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["enabled"])
        self.assertFalse(self.root.exists())

    def test_copy_of_monolith_has_no_external_runtime_dependency(self):
        copy = self.base / "corix.sh"; shutil.copyfile(SCRIPT, copy)
        result = self.invoke("status", script=copy)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.root.exists())

    def test_enabled_rpc_does_not_run_native_recovery_or_create_locks(self):
        self.enable()
        before = sorted(str(p) for p in self.root.rglob("*"))
        result = self.invoke("rpc", "--stdio", data=self.request())
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["recovery"], "explicit-native-operation")
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)

    def test_network_context_selected_before_machine_request(self):
        self.enable("alpha")
        result = self.invoke("--network", "alpha", "rpc", "--stdio", data=self.request())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["network_id"], "alpha")
        result = self.invoke("--network", "../other", "status")
        self.assertEqual(result.returncode, 2)

    def test_bad_config_and_cross_network_config_rejected(self):
        config = self.enable()
        result = self.invoke("--network", "alpha", "--config", str(config), "status")
        self.assertEqual(result.returncode, 2)
        for body in ("[ziokt]\nenabled=true\n", "[ziokt]\nenabled=TRUE\nenabled=FALSE\n", "[ziokt]\ncommand=echo\n"):
            config.write_text(body)
            self.assertEqual(self.invoke("status").returncode, 2)

    def test_write_methods_wrong_scope_and_framing_rejected(self):
        self.enable()
        for data in (self.request(method="operation.commit"), self.request(provider_id="other"),
                     self.request() + self.request(), self.request().rstrip("\n")):
            result = self.invoke("rpc", "--stdio", data=data)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
