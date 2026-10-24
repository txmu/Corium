#!/usr/bin/env python3
"""Read-only recovery preflight. A plan cannot activate either chain.

The native prefix replay is a separately produced input, not an independent
proof. This tool never signs, mines, deletes history, changes routing, or clears
an operational safety hold.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import dna_protocol as dna
import cooperative_protocol as coop


def snapshot(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        blocks=db.execute('SELECT * FROM blocks ORDER BY height').fetchall()
        transactions=db.execute('SELECT * FROM transactions ORDER BY hash').fetchall()
        proofs=db.execute('SELECT * FROM block_work ORDER BY hash').fetchall()
    dna.require(blocks and all(row[0]==i for i,row in enumerate(blocks)),'contiguous archived heights')
    return {'blocks':blocks,'transactions':transactions,'block_work':proofs}


def plan(old_chain,prefix_chain,genesis,state,first_new_height=51,target_height=64):
    dna.require(first_new_height==51 and target_height==64,'operator-authorized 51..64 recovery boundary')
    old=snapshot(old_chain);prefix=snapshot(prefix_chain)
    dna.require(len(prefix['blocks'])==first_new_height,'replayed prefix must end exactly at 50')
    dna.require(old['blocks'][:first_new_height]==prefix['blocks'],'preserved prefix differs from archive')
    hashes={row[1]for row in prefix['blocks']}
    dna.require(not prefix['block_work'],'legacy prefix must have no auxiliary PoW rows')
    committed={tx for row in prefix['blocks']for tx in json.loads(row[6])}
    dna.require(all(row[0]in committed and row[6]is not None and row[6]<first_new_height
                    for row in prefix['transactions']),'only canonically committed prefix transactions')
    dna.require({row[0]for row in prefix['transactions']}==committed,'missing prefix transaction bodies')
    state_data=dna.loads(Path(state).read_text(),16*1024*1024)
    state_hash=hashlib.sha256(dna.encoded(state_data)).hexdigest()
    original_root=hashlib.sha256(b'Corium/Recovery/archive/v1\0'+dna.encoded(old)).hexdigest()
    anchor=prefix['blocks'][-1]
    result={'schema':'corium.recovery-transition-plan.v1','activation_performed':False,
      'operator_decision':{'first_new_main_height':51,'initial_main_target_height':64,
                           'old_history_role':'DNA sidechain after validated activation'},
      'archive':{'block_count':len(old['blocks']),'tip_height':old['blocks'][-1][0],
                 'tip_hash':old['blocks'][-1][1],'record_root':original_root,
                 'full_legacy_history_verified':False},
      'main':{'status':'replayed-prefix-only','checkpoint_height':anchor[0],'checkpoint_hash':anchor[1],
              'replayed_state_commitment':state_hash,'new_blocks_required':14,
              'genesis_configuration_sha256':hashlib.sha256(Path(genesis).read_bytes()).hexdigest(),
              'protocol':'native recovery; full transaction/chain domain integration required'},
      'side':{'status':'legacy archive preserved; DNA not active',
              'first_possible_dna_height':old['blocks'][-1][0]+1,'protocol':'DNA duplex / authenticated RNA',
              'activation_requires_explicit_legacy_checkpoint':True},
      'cooperative_charter':coop.CHARTER,
      'trust_dependencies':['supplied legacy genesis configuration','native prefix replay implementation',
                           'legacy core_gpg_authority input','explicit sidechain legacy checkpoint'],
      'release_blockers':['native block/transaction/signature domain integration',
                          'uniform accept/sync/reorg/replay and wallet validation',
                          'atomic persistent RNA replay protection in native delivery',
                          'cooperative native state and asset/control transition integration',
                          'actual new blocks 51..64 and replayed state comparison',
                          'distinct protocol process tests and atomic routing cutover'],
      'production_history_modified':False}
    result['plan_digest']=hashlib.sha256(b'Corium/Recovery/plan/v1\0'+dna.encoded(result)).hexdigest()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('old-chain','prefix-chain','genesis','state'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(plan(args.old_chain,args.prefix_chain,args.genesis,args.state),indent=2))
