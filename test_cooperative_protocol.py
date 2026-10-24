import copy
import unittest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature
import cooperative_protocol as coop

class CooperativeTests(unittest.TestCase):
    def setUp(self):
        self.keys=[ec.generate_private_key(ec.SECP256K1())for _ in range(6)]
        self.state=coop.empty('a'*64)
        for name,keys in [('workers',self.keys[:3]),('farmers',self.keys[3:])]:
            command=self.command(name,'create',{'members':[coop.public_key(k)for k in keys]},1)
            self.state=coop.apply(self.state,command,[coop.endorse(command,k)for k in keys])
    def command(self,cid,action,args,seq=None):
        return {'schema':'corium.cooperative-command.v1','chain':self.state['chain'],'cooperative':cid,
                'sequence':seq or self.state['cooperatives'][cid]['sequence']+1,'previous_state':coop.state_root(self.state),
                'action':action,'arguments':args}
    def run_command(self,command,keys):
        return coop.apply(self.state,command,[coop.endorse(command,k)for k in keys])
    def test_mergers_control_sale_and_capital_votes_rejected(self):
        original=copy.deepcopy(self.state)
        for action in coop.FORBIDDEN:
            command=self.command('workers',action,{})
            with self.assertRaisesRegex(ValueError,'anti-takeover'):self.run_command(command,self.keys)
        command=self.command('workers','federate',{'partner':'farmers','capital':10**12})
        with self.assertRaises(ValueError):self.run_command(command,self.keys)
        self.assertEqual(self.state,original)
    def test_duplicate_votes_and_insufficient_members_do_not_pass(self):
        command=self.command('workers','federate',{'partner':'farmers'})
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_command(command,[self.keys[0]]*3)
        with self.assertRaisesRegex(ValueError,'supermajority'):self.run_command(command,self.keys[:2]+self.keys[3:])
    def test_federation_keeps_independent_governance_and_unilateral_exit(self):
        command=self.command('workers','federate',{'partner':'farmers'})
        joined=self.run_command(command,self.keys)
        for cid in ('workers','farmers'):
            self.assertEqual(joined['cooperatives'][cid]['members'],self.state['cooperatives'][cid]['members'])
        self.state=joined
        command=self.command('workers','unfederate',{'partner':'farmers'})
        left=self.run_command(command,self.keys[:3])
        self.assertEqual(left['cooperatives']['workers']['federations'],[])
        self.assertEqual(left['cooperatives']['farmers']['federations'],[])
    def test_members_exit_and_admission_need_actual_consent(self):
        member=coop.identity(coop.public_key(self.keys[0]));command=self.command('workers','leave',{'member':member})
        self.assertNotIn(member,self.run_command(command,[self.keys[0]])['cooperatives']['workers']['members'])
        with self.assertRaises(ValueError):self.run_command(command,[self.keys[1]])
        new=ec.generate_private_key(ec.SECP256K1());command=self.command('workers','admit',{'public_key':coop.public_key(new)})
        with self.assertRaises(ValueError):self.run_command(command,self.keys[:3])
        admitted=self.run_command(command,self.keys[:3]+[new]);self.assertEqual(len(admitted['cooperatives']['workers']['members']),4)
    def test_cross_chain_stale_state_and_resigned_replay_rejected(self):
        command=self.command('workers','leave',{'member':coop.identity(coop.public_key(self.keys[0]))})
        for change in [{'chain':'b'*64},{'previous_state':'c'*64},{'sequence':99}]:
            with self.assertRaises(ValueError):self.run_command({**command,**change},[self.keys[0]])
        proof=coop.endorse(command,self.keys[0]);altered={**command,'arguments':{'member':coop.identity(coop.public_key(self.keys[1]))}}
        with self.assertRaises(InvalidSignature):coop.apply(self.state,altered,[proof])
