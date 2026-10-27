"""One real signed mainnet-domain block and canonical state rebuild."""
import json
import shlex
import sqlite3
from cryptography.hazmat.primitives import serialization
import cooperative_protocol as coop
import cooperative_consensus as consensus
from test_core import Fixture


class NativeCooperativeTests(Fixture):
    network_id='ziokt-main'

    def test_signed_admission_local_mining_and_replay_use_identical_registry_root(self):
        key=serialization.load_pem_private_key((self.etc/'identity.key').read_bytes(),None)
        with sqlite3.connect(self.chain) as db:state=consensus.state_at(db,self.network_id,1)
        command={'schema':'corium.cooperative-command.v1','chain':state['chain'],'cooperative':'workers',
                 'sequence':1,'previous_state':coop.state_root(state),'action':'create','arguments':{'members':[coop.public_key(key)]}}
        payload={'command':command,'endorsements':[coop.endorse(command,key)]}
        self.run_core('blockchain_create_transaction cooperative_command '+shlex.quote(json.dumps(payload))+' >/dev/null; blockchain_mine_block >/dev/null')
        with sqlite3.connect(self.chain) as db:
            root=coop.state_root(consensus.state_at(db,self.network_id,2))
            self.assertEqual(db.execute("SELECT count(*) FROM transactions WHERE type='cooperative_command' AND block_height=1").fetchone()[0],1)
        self.run_core('_internal_rebuild_derived_state')
        with sqlite3.connect(self.chain) as db:self.assertEqual(coop.state_root(consensus.state_at(db,self.network_id,2)),root)
        self.run_core('blockchain_create_transaction cooperative_command '+shlex.quote(json.dumps(payload)),ok=False)
