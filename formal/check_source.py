#!/usr/bin/env python3
"""Detect drift in manually reviewed source mappings; this is not a translator."""
import argparse
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'formal/source-map.json'
GROUPS = {
    'Kahn fanout and dependency filtering': ['dep_resolve_topological'],
    'Integer XOR': ['kademlia_distance'],
    'Semantic row normalization': ['_internal_semantic_state'],
    'Exodus tally': ['_internal_verify_exodus_quorum'],
    'Merkle and checkpoint codec': ['_internal_ibc_codec', '_internal_generate_merkle_siblings',
                                    '_internal_ibc_generate_proof', '_internal_verify_merkle_proof',
                                    '_internal_verify_hash_chain_proof'],
    'Database snapshot depth': ['db_begin_transaction', 'db_commit_transaction',
                                '_internal_db_restore_snapshot'],
    'Checked replay and reorganization': ['_internal_replay_chain_state', '_blockchain_reorganize_to'],
    'Cooperative admission and canonical application': ['_validate_single_transaction','blockchain_create_transaction','blockchain_mine_block'],
    'Bootstrap history safety and explicit discovery': ['_internal_consensus_safety_check', 'dht_bootstrap', 'blockchain_create_genesis_block'],
}


def hashes():
    text = (ROOT / 'corix_v108.sh').read_text()
    result = {}
    for names in GROUPS.values():
        for name in names:
            start = re.search(r'^' + re.escape(name) + r'\(\) [({]\n', text, re.M)
            if start is None:
                raise ValueError(f'Missing source function: {name}')
            end = re.search(r'^[)}]\n', text[start.end():], re.M)
            if end is None:
                raise ValueError(f'Missing source boundary: {name}')
            body = text[start.start():start.end() + end.end()]
            result[name] = hashlib.sha256(body.encode()).hexdigest()
    for relative in ('consensus_hold.py','formal/contracts.json','formal/generate_guards.py','cooperative_protocol.py','cooperative_consensus.py','work_consensus.py'):
        result['file:'+relative]=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='Record a manually reviewed mapping revision')
    args = parser.parse_args()
    current = hashes()
    if args.update:
        MANIFEST.write_text(json.dumps({'mapping_kind': 'manual; hashes detect drift, not equivalence',
                                      'groups': GROUPS, 'sha256': current}, indent=2) + '\n')
    recorded = json.loads(MANIFEST.read_text())
    if recorded['groups'] != GROUPS or recorded['sha256'] != current:
        raise SystemExit('Source mapping changed: review the model and update source-map.json explicitly')
    print(f'Source mapping: {len(current)} function hashes match (manual correspondence, not a proof).')


if __name__ == '__main__':
    main()
