"""Real native owner/epoch validation and IBC checkpoint generation for names."""
import hashlib
import json
import shlex
import sqlite3
import time
from test_core import Fixture

class NamingIBCTests(Fixture):
    def payload(self,epoch=1,root='corium'):
        return {'target_chain_id':'other','message_type':'ZIOKT_NAME_BINDING_V1',
                'message_payload':{'namespace':'shared-one','root':root,'source_chain_id':'default',
                  'epoch':epoch,'expires_at':int(time.time())+300,'record':{'network_id':'shared-one'}}}
    def transaction(self,payload):
        timestamp=int(time.time());data=json.dumps(payload,separators=(',',':'))
        raw='{"type":"ibc_dispatch","data":'+data+',"timestamp":'+str(timestamp)+'}';digest=hashlib.sha256(raw.encode()).hexdigest()
        with sqlite3.connect(self.chain) as db:db.execute('INSERT OR REPLACE INTO transactions VALUES (?,?,?,?,?,?,NULL)',(digest,'ibc_dispatch',data,self.sign(raw),self.pem,timestamp))
        return digest
    def validate(self,digest,ok=True):return self.run_core('declare -A state=() cache=(); _validate_single_transaction '+digest+' "" "" 1 state cache',ok)
    def test_current_nns_owner_and_exact_source_scope(self):
        self.validate(self.transaction(self.payload()))
        for change in ({'root':'not-owned'},{'source_chain_id':'wrong'},{'expires_at':1},{'epoch':0}):
            payload=self.payload();payload['message_payload'].update(change)
            self.validate(self.transaction(payload),False)
    def test_registration_cannot_overwrite_another_owner(self):
        with sqlite3.connect(self.forum) as db:db.execute("UPDATE nns_records SET owner_id=? WHERE domain_name='corium'",('f'*64,))
        payload={'domain_name':'corium','target_hash':'a'*64,'proof_of_genesis_contribution':{'probes':[]}}
        timestamp=int(time.time());data=json.dumps(payload,separators=(',',':'))
        raw='{"type":"nns_register","data":'+data+',"timestamp":'+str(timestamp)+'}';digest=hashlib.sha256(raw.encode()).hexdigest()
        with sqlite3.connect(self.chain) as db:db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,NULL)',(digest,'nns_register',data,self.sign(raw),self.pem,timestamp))
        self.validate(digest,False)

    def test_mine_checkpoint_proof_and_epoch_replay(self):
        payload=self.payload();tx=self.transaction(payload)
        self.run_core('blockchain_mine_block')
        proof=json.loads(self.run_core('_internal_ibc_generate_proof '+tx).stdout)
        self.assertEqual(proof['format'],'CORIUM_IBC_CHECKPOINT_V2')
        self.assertEqual(proof['merkle_proof']['target_tx_hash'],tx)
        other=self.transaction(self.payload())
        self.run_core('declare -A state=() cache=(); _validate_single_transaction '+other+' "" "" 2 state cache',False)
        next_tx=self.transaction(self.payload(epoch=2))
        self.run_core('declare -A state=() cache=(); _validate_single_transaction '+next_tx+' "" "" 2 state cache')

if __name__=='__main__':
    import unittest
    unittest.main()
