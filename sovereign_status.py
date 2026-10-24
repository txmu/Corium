#!/usr/bin/env python3
"""Sovereign Network Status and Management Dashboard.

Provides detailed status inspection for node operators, light clients, and dashboards:
- Consensus mode & role separation (PoW mining, OpenCI compute, PoS governance, P2P relay, Full node)
- Chain height, cumulative work, difficulty, target, target block spacing
- Last block producer & mining state
- Lean 4 formal verification metrics
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import re
import sys
from typing import Dict, Any

from consensus_core import (
    ConsensusValidationCore,
    target_from_bits,
    bits_from_target,
    TARGET_SPACING,
    WORK_V2_ACTIVATION_HEIGHT
)


def get_sovereign_status(corium_root: str, network_id: str = 'ziokt-main') -> Dict[str, Any]:
    chain_db = os.path.join(corium_root, 'var/lib/corix/networks', network_id, 'blockchain/chain.db')
    if not os.path.exists(chain_db):
        chain_db = os.path.join(corium_root, 'blockchain.db')

    status: Dict[str, Any] = {
        'network_id': network_id,
        'corium_root': corium_root,
        'chain_db': chain_db,
        'online': None  # A readable DB does not prove a running network service.
    }
    hold_path=Path(corium_root).resolve().parent/'config/consensus-safety-hold.json'
    hold=None
    if hold_path.is_file():
        try:
            value=json.loads(hold_path.read_text())
            if type(value) is not dict or value.get('schema')!='ziokt.consensus-safety-hold.v1' or type(value.get('active')) is not bool:
                raise ValueError('Malformed safety hold')
            hold={key:value[key] for key in ('active','reason_code','first_unverified_height') if key in value}
        except (OSError,ValueError,TypeError):
            hold={'active':True,'reason_code':'INVALID_HOLD_EVIDENCE'}
    status['consensus_safety_hold']=hold
    status['full_history_verified']=False

    if not os.path.exists(chain_db):
        status['error'] = f'Blockchain database not found at {chain_db}'
        return status

    core = ConsensusValidationCore(chain_db, network_id)
    tip = core.get_tip()

    if not tip:
        status['height'] = -1
        status['tip_hash'] = None
        status['consensus_mode'] = 'uninitialized'
        return status

    height = tip['height']
    tip_hash = tip['hash']
    total_weight = tip['total_weight']
    timestamp = tip['timestamp']
    producer = tip['validator']

    # Consensus mode
    if height < WORK_V2_ACTIVATION_HEIGHT:
        consensus_mode = 'legacy-pos'
        diff_bits = 0
        target_int = 0
    else:
        consensus_mode = 'pow-v2 (Work v2 Native PoW)'
        diff_bits = 4
        target_int = target_from_bits(4)
        if 'work' in tip and 'target' in tip['work']:
            target_int = int(tip['work']['target'])
            diff_bits = bits_from_target(target_int)

    # Mempool
    with core.get_connection() as db:
        pending_count = db.execute('SELECT COUNT(*) FROM transactions WHERE block_height IS NULL').fetchone()[0]
        # Check node stake in validators table
        node_pub_file = os.path.join(corium_root, 'etc/identity.key.pub')
        node_stake = 0
        if os.path.exists(node_pub_file):
            pub_text = open(node_pub_file).read().strip()
            row = db.execute("SELECT stake, status FROM validators WHERE public_key = ? OR public_key_hash = ?", (pub_text, producer)).fetchone()
            if row:
                node_stake = int(row[0])

    # Mining settings
    pause_file = os.path.join(corium_root, 'pause_mining')
    allow_empty_file = os.path.join(corium_root, 'allow_empty_blocks')
    env_mining = os.environ.get('CORIUM_MINING_ENABLED', '1')
    env_allow_empty = os.environ.get('CORIUM_ALLOW_EMPTY_BLOCKS', '0')

    is_mining_enabled = (env_mining != '0') and (not os.path.exists(pause_file)) and not (hold and hold.get('active'))
    is_empty_blocks_allowed = (env_allow_empty == '1') or (os.path.exists(allow_empty_file))

    # Formal Verification Coverage
    formal_coverage = {
        'engine': 'Lean 4 (version 4.19.0)',
        'modules': ['Consensus', 'StateMachine', 'Governance', 'OpenCI', 'Privacy', 'ContentFabric', 'Models', 'Implementation', 'Refinements'],
        'theorems_verified': None,
        'theorem_declarations': sum(len(re.findall(r'^theorem\s+\w+',file.read_text(),re.M)) for file in Path(__file__).with_name('formal').glob('*.lean')) or None,
        'axioms_audit': 'not observed by this status query; consult the exact source CI receipt',
        'differential_testing': 'Python comparisons against transcribed formulas; not a production refinement proof'
    }

    # Distinct Node Roles
    roles = {
        'corium_pow_miner': 'Configured; runtime not observed' if is_mining_enabled else 'Disabled or safety-held',
        'openci_compute_worker': 'Runtime not observed',
        'p2p_relayer': 'Runtime and remote peers not observed',
        'ziokt_effort_node': 'Runtime not observed',
        'pos_governance_validator': f'Registered (Stake: {node_stake})' if node_stake > 0 else 'Unstaked (Stake: 0, Sovereign Citizen)',
        'full_verification_node': 'Blocked by history provenance' if hold and hold.get('active') else 'Full history verification not established'
    }

    status.update({
        'height': height,
        'tip_hash': tip_hash,
        'cumulative_work': total_weight,
        'consensus_mode': consensus_mode,
        'difficulty_bits': diff_bits,
        'target_hex': hex(target_int),
        'target_spacing_seconds': TARGET_SPACING,
        'last_block_producer': producer,
        'timestamp': timestamp,
        'mempool_transactions': pending_count,
        'mining_configured': {
            'enabled': is_mining_enabled,
            'allow_empty_blocks': is_empty_blocks_allowed,
            'hashrate_limit': 'Unlimited (Local CPU / Background Worker)'
        },
        'roles': roles,
        'formal_verification': formal_coverage
    })

    return status


def print_pretty_status(status: Dict[str, Any]):
    print("================================================================================")
    print("           ZIOKT SOVEREIGN NETWORK — NODE & CONSENSUS DASHBOARD")
    print("================================================================================")
    print(f"Network ID:                  {status.get('network_id')}")
    print(f"Current Height:              {status.get('height')}")
    print(f"Chain Tip Hash:              {status.get('tip_hash')}")
    print(f"Cumulative Chain Work:       {status.get('cumulative_work')} units")
    print(f"Consensus Engine:            {status.get('consensus_mode')}")
    print(f"Current Difficulty:          {status.get('difficulty_bits')} bits (Target: {status.get('target_hex')[:18]}...)")
    print(f"Expected Block Interval:     {status.get('target_spacing_seconds')} seconds")
    print(f"Last Block Miner:            {status.get('last_block_producer')}")
    print(f"Mempool Pending Tx:          {status.get('mempool_transactions')}")
    print("--------------------------------------------------------------------------------")
    print("NODE ROLES & PERMISSIONS:")
    roles = status.get('roles', {})
    for role, state in roles.items():
        role_label = role.replace('_', ' ').title()
        print(f"  * {role_label:<28}: {state}")
    print("--------------------------------------------------------------------------------")
    mining = status.get('mining_configured', {})
    print("MINING & BLOCK PRODUCTION CONTROLS:")
    print(f"  * Local Mining Enabled:    {mining.get('enabled')}")
    print(f"  * Allow Empty Blocks:      {mining.get('allow_empty_blocks')}")
    print("--------------------------------------------------------------------------------")
    fv = status.get('formal_verification', {})
    print("FORMAL VERIFICATION & LEAN 4 ASSURANCE:")
    print(f"  * Verifier:                {fv.get('engine')}")
    print(f"  * Modules Checked:         {', '.join(fv.get('modules', []))}")
    print(f"  * Theorem declarations:    {fv.get('theorem_declarations')} (runtime proof checking not observed)")
    print(f"  * Axioms Audit:            {fv.get('axioms_audit')}")
    print(f"  * Differential Alignment:  {fv.get('differential_testing')}")
    print("================================================================================")


def main():
    parser = argparse.ArgumentParser(description="Query Ziokt Sovereign Network node status.")
    parser.add_argument('--root', default=os.environ.get('CORIUM_ROOT', '/home/admin/.local/share/ziokt-production/corium'), help='CORIUM_ROOT path')
    parser.add_argument('--network', default=os.environ.get('CORIUM_NETWORK_ID_OVERRIDE', 'ziokt-main'), help='Network ID')
    parser.add_argument('--json', action='store_true', help='Output JSON format')
    args = parser.parse_args()

    status = get_sovereign_status(args.root, args.network)
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print_pretty_status(status)


if __name__ == '__main__':
    main()
