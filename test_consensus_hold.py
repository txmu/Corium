import json
from pathlib import Path
import tempfile
import unittest
import hashlib
from consensus_hold import start_permitted
from test_core import Fixture


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


class NativeMutationHoldTests(Fixture):
    def test_all_canonical_mutation_entries_reject_before_writing(self):
        path=self.root/'hold.json'
        path.write_text(json.dumps({'schema':'ziokt.consensus-safety-hold.v1','active':True}));path.chmod(0o600)
        self.env['CORIUM_CONSENSUS_HOLD_FILE']=str(path)
        before=hashlib.sha256(self.chain.read_bytes()).hexdigest()
        for command in ('blockchain_mine_block',
                        '_blockchain_reorganize_to '+'a'*64+' 127.0.0.1 9999',
                        '_internal_sync_fetch_new_blocks_to_stage "$CORIUM_ROOT/stage.db" 0',
                        '_internal_import_phoenix_state "$CORIUM_ROOT/missing.json"',
                        '_internal_rebuild_derived_state'):
            with self.subTest(entry=command.split()[0]):
                result=self.run_core(command,ok=False)
                self.assertIn('CONSENSUS_SAFETY_HOLD',result.stderr)
                self.assertEqual(hashlib.sha256(self.chain.read_bytes()).hexdigest(),before)
