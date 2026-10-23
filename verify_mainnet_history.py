#!/usr/bin/env python3
"""Independent Mainnet History Verifier for ziokt-main.

Checks chain structure and governed Work v2 proofs against a supplied database.
Legacy PoS authorization, transaction execution, governance reconstruction and
state commitments are NOT independently replayed. Success is partial verification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import os
import subprocess
import tempfile
import re
from typing import Dict, Any, Optional

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

GENESIS_HASH = '599b7512c4ffb640520433f0772f00e78198ad958f444d25459dbca8c38ce0fa'
NETWORK_ID = 'ziokt-main'
WORK_V2_ACTIVATION_HEIGHT = 64
WORK_V2_ACTIVATION_COMMITMENT = '9caf67936f6d1881296b97f5a5524f344ab06547d4eec78fc352f695228fa8df'


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


import work_consensus as work


def require(condition, message):
    if not condition:
        raise ValueError(message)


def replay_native_history(root: str, height: int, network: str = NETWORK_ID,
                          source: Optional[str] = None) -> Dict[str, Any]:
    """Rebuild native state in scratch DBs, including legacy validation.

    Uses the native interpreter and genesis configuration, not an independent
    implementation or an on-chain state-root proof. Never replaces live DBs.
    """
    require(type(height) is int and height >= 0, 'Invalid replay height')
    script = Path(source) if source else Path(__file__).with_name('corix_v108.sh')
    env = dict(os.environ, CORIUM_ROOT=str(Path(root).resolve()),
               CORIUM_NETWORK_ID_OVERRIDE=network, CORIUM_TEST_NO_DAEMONS='1')
    command = '''set -eE
source "$1"
trap 'printf "NATIVE_REPLAY_FAILURE line=%s height=%s\\n" "$LINENO" "${bh:-setup}" >&2' ERR
load_config || exit 1
_internal_replay_chain_state "$2" "$3"
BLOCKCHAIN_DB="$3/chain.db"
FORUM_DB="$3/forum.db"
DHT_DB="$3/dht.db"
INSTALLED_DB="$3/installed"
_internal_semantic_state
'''
    with tempfile.TemporaryDirectory(prefix='corium-history-replay-') as directory:
        result = subprocess.run(['bash', '-c', command, 'history-replay', str(script.resolve()),
                                 str(height), directory], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        if result.returncode:
            markers = re.findall(r'NATIVE_REPLAY_FAILURE line=[0-9]+ height=(?:[0-9]+|setup)', result.stderr)
            location = ': ' + markers[0] if markers else ''
            raise ValueError('Native history replay rejected the supplied history' + location)
        state = json.loads(result.stdout.splitlines()[-1])
        return {'status': 'NATIVE_REPLAY_COMPLETED', 'height': height,
                'reconstructed_state_digest': sha256_hex(canonical_json(state)),
                'source_sha256': sha256_hex(script.read_bytes()),
                'legacy_signatures_transactions_and_governance': 'checked_by_native_replay',
                'independent_implementation': False, 'on_chain_state_commitment_verified': False,
                'trust_dependencies': ['genesis configuration', 'native interpreter', 'available immutable objects and package verifiers']}


def verify_history(db_path: str, max_height: Optional[int] = None, *, require_full: bool = False) -> Dict[str, Any]:
    if require_full:
        raise ValueError('Full independent history verification is unavailable: legacy PoS, '
                         'transactions, governance and application state must be replayed')
    require(max_height is None or (type(max_height) is int and max_height >= 0), 'Invalid maximum height')
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        # 1. Verify genesis
        genesis_row = conn.execute('SELECT * FROM blocks WHERE height = 0').fetchone()
        require(genesis_row is not None, 'Genesis block missing')
        require(genesis_row['hash'] == GENESIS_HASH, f'Genesis hash {genesis_row["hash"]} != expected {GENESIS_HASH}')

        total_blocks = conn.execute('SELECT COUNT(*) FROM blocks').fetchone()[0]
        max_chain_height = conn.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
        limit_height = min(max_chain_height, max_height) if max_height is not None else max_chain_height

        print(f'[INFO] Verifying {limit_height + 1} blocks from genesis up to height {limit_height}...')

        parent_hash = GENESIS_HASH
        parent_height = 0
        parent_time = genesis_row['timestamp']
        parent_weight = genesis_row['total_weight']

        legacy_count = 0
        pow_count = 0

        for h in range(1, limit_height + 1):
            row = conn.execute('SELECT * FROM blocks WHERE height = ?', (h,)).fetchone()
            require(row is not None, f'Missing block at height {h}')
            b = dict(row)

            require(b['previous_hash'] == parent_hash, f'Height {h} broken parent link: {b["previous_hash"]} != {parent_hash}')
            require(b['timestamp'] >= parent_time, f'Height {h} timestamp regression: {b["timestamp"]} < {parent_time}')

            txs = json.loads(b['transactions'])
            require(isinstance(txs, list), f'Height {h} transactions not a list')

            if h < WORK_V2_ACTIVATION_HEIGHT:
                # Legacy consensus
                require(b['total_weight'] > parent_weight, f'Height {h} total_weight must increase')
                legacy_count += 1
            else:
                # Work v2 PoW
                proof_row = conn.execute('SELECT proof FROM block_work WHERE hash = ?', (b['hash'],)).fetchone()
                require(proof_row is not None, f'Height {h} missing PoW proof in block_work')
                block_cand = {k: b[k] for k in ('height', 'previous_hash', 'timestamp', 'validator', 'signature')}
                block_cand['transactions'] = txs
                block_cand['work'] = json.loads(proof_row[0])
                res = work.verify(conn, NETWORK_ID, block_cand, b['hash'])
                require(res['work_verified'], f'Height {h} work verification failed')
                require(b['total_weight'] == res['total_weight'], f'Height {h} total_weight mismatch against governed policy')
                pow_count += 1

            parent_hash = b['hash']
            parent_height = h
            parent_time = b['timestamp']
            parent_weight = b['total_weight']

        print(f'[PARTIAL] Checked {limit_height + 1} blocks; full state replay NOT performed:')
        print(f'  - Genesis: {GENESIS_HASH}')
        print(f'  - Legacy PoS blocks (1..{WORK_V2_ACTIVATION_HEIGHT - 1}): {legacy_count}')
        print(f'  - Work v2 PoW blocks ({WORK_V2_ACTIVATION_HEIGHT}..{limit_height}): {pow_count}')
        print(f'  - Chain Tip Hash: {parent_hash}')
        print(f'  - Chain Cumulative Work / Total Weight: {parent_weight}')

        return {
            'status': 'PARTIALLY_VERIFIED',
            'full_history_verified': False,
            'coverage': {'parent_links': True, 'timestamps': True, 'pow_signatures_and_work': True,
                         'legacy_pos_signatures': False, 'transaction_execution': False,
                         'governance_reconstructed': False, 'application_state_commitments': False},
            'trust_dependencies': ['supplied database governance and parent weights', 'configured genesis hash'],
            'genesis_hash': GENESIS_HASH,
            'network_id': NETWORK_ID,
            'verified_blocks': limit_height + 1,
            'tip_height': limit_height,
            'tip_hash': parent_hash,
            'tip_total_weight': parent_weight,
            'legacy_pos_blocks': legacy_count,
            'pow_v2_blocks': pow_count,
            'work_v2_activation_height': WORK_V2_ACTIVATION_HEIGHT,
            'work_v2_activation_commitment': WORK_V2_ACTIVATION_COMMITMENT
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Verify ziokt-main chain history from genesis.')
    parser.add_argument('--db', default='/home/admin/.local/share/ziokt-production/corium/var/lib/corix/networks/ziokt-main/blockchain/chain.db', help='Path to chain.db')
    parser.add_argument('--max-height', type=int, default=None, help='Max height to verify')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    parser.add_argument('--require-full', action='store_true', help='Fail closed if independent full replay is unavailable')
    parser.add_argument('--native-root', help='Also rebuild native legacy/governance/application state in scratch databases (180s limit)')
    args = parser.parse_args()

    report = verify_history(args.db, args.max_height, require_full=args.require_full)
    if args.native_root:
        expected = Path(args.native_root) / 'var/lib/corix/networks' / NETWORK_ID / 'blockchain/chain.db'
        require(expected.resolve() == Path(args.db).resolve(), 'Native root and supplied chain DB differ')
        report['native_replay'] = replay_native_history(args.native_root, report['tip_height'])
    if args.json:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
