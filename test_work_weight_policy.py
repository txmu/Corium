"""Pure adapter arithmetic/hash vectors, not mainnet activation evidence."""
import copy
import unittest
from work_weight_policy import SCHEMA,PROOF,PolicyError,commitment,weight_at,work_digest,verify_work


class WorkWeightPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy={'schema':SCHEMA,'network':'test-pow','genesis':'a'*64,'activation_height':10,
                     'difficulty_bits':4,'weights':[{'from_height':10,'weight':1000},{'from_height':20,'weight':500}]}
        self.context={'height':10,'parent':'b'*64,'body':'c'*64,'miner':'d'*64}

    def proof(self):
        nonce=0
        while int(work_digest(self.policy,self.context,nonce),16)>=2**252:nonce+=1
        return {'schema':PROOF,'policy':commitment(self.policy),'nonce':nonce}

    def test_valid_work_receives_unconditional_height_weight_without_stake(self):
        result=verify_work(self.policy,self.context,self.proof(),network='test-pow',genesis='a'*64,parent_weight=1000)
        self.assertEqual((result['weight'],result['total_weight']),(1000,2000))
        self.assertFalse(result['network_activated']);self.assertFalse(result['ledger_modified'])
        self.assertEqual(weight_at(self.policy,19,network='test-pow',genesis='a'*64),1000)
        self.assertEqual(weight_at(self.policy,20,network='test-pow',genesis='a'*64),500)

    def test_replay_scope_and_invalid_work_never_grant_weight(self):
        proof=self.proof()
        for change in ({'network':'other'},{'genesis':'e'*64},{'parent_weight':2**63-1}):
            args={'network':'test-pow','genesis':'a'*64,'parent_weight':0,**change}
            with self.assertRaises(PolicyError):verify_work(self.policy,self.context,proof,**args)
        changed=copy.deepcopy(self.policy);changed['weights'][0]['weight']=999
        with self.assertRaises(PolicyError):verify_work(changed,self.context,proof,network='test-pow',genesis='a'*64,parent_weight=0)
        wrong=0
        while int(work_digest(self.policy,self.context,wrong),16)<2**252:wrong+=1
        with self.assertRaises(PolicyError):verify_work(self.policy,self.context,{**proof,'nonce':wrong},network='test-pow',genesis='a'*64,parent_weight=0)
        for key in ('parent','body','miner'):
            context={**self.context,key:'e'*64}
            self.assertNotEqual(work_digest(self.policy,context,proof['nonce']),work_digest(self.policy,self.context,proof['nonce']))

    def test_schedule_boundaries_and_malformed_input(self):
        with self.assertRaises(PolicyError):weight_at(self.policy,9,network='test-pow',genesis='a'*64)
        for weights in ([],[{'from_height':11,'weight':1000}],[{'from_height':10,'weight':True}],
                        [{'from_height':10,'weight':1},{'from_height':10,'weight':2}],
                        [{'from_height':10,'weight':2**63}]):
            with self.assertRaises(PolicyError):commitment({**self.policy,'weights':weights})
        with self.assertRaises(PolicyError):work_digest(self.policy,self.context,True)
        with self.assertRaises(PolicyError):commitment({**self.policy,'node_count':3})
        self.assertEqual(commitment(self.policy),commitment(dict(reversed(list(self.policy.items())))))
