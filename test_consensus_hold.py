import json
from pathlib import Path
import tempfile
import unittest
from consensus_hold import start_permitted


class ConsensusHoldTests(unittest.TestCase):
    def test_boot_guard_requires_absent_or_explicitly_cleared_private_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hold.json'
            self.assertTrue(start_permitted(path))
            for value,expected in (({'schema':'ziokt.consensus-safety-hold.v1','active':True},False),
                                   ({'schema':'ziokt.consensus-safety-hold.v1','active':False},True),
                                   ({'active':False},False),([],False)):
                path.write_text(json.dumps(value));path.chmod(0o600)
                self.assertEqual(start_permitted(path),expected)
            path.chmod(0o644);self.assertFalse(start_permitted(path))
            link=Path(directory)/'alias';link.symlink_to(path)
            self.assertFalse(start_permitted(link))
