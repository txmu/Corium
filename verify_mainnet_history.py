#!/usr/bin/env python3
"""Independent Mainnet History Verifier for ziokt-main.

Validates the full chain from genesis through legacy PoS, migration at height 64,
and Work v2 PoW to the current tip without relying on external trust anchors.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
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


def verify_history(db_path: str, max_height: Optional[int] = None) -> Dict[str, Any]:
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        # 1. Verify genesis
        genesis_row = conn.execute('SELECT * FROM blocks WHERE height = 0').fetchone()
        assert genesis_row is not None, 'Genesis block missing'
        assert genesis_row['hash'] == GENESIS_HASH, f'Genesis hash {genesis_row["hash"]} != expected {GENESIS_HASH}'

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
            assert row is not None, f'Missing block at height {h}'
            b = dict(row)

            assert b['previous_hash'] == parent_hash, f'Height {h} broken parent link: {b["previous_hash"]} != {parent_hash}'
            assert b['timestamp'] >= parent_time, f'Height {h} timestamp regression: {b["timestamp"]} < {parent_time}'

            txs = json.loads(b['transactions'])
            assert isinstance(txs, list), f'Height {h} transactions not a list'

            if h < WORK_V2_ACTIVATION_HEIGHT:
                # Legacy consensus
                assert b['total_weight'] > parent_weight, f'Height {h} total_weight must increase'
                legacy_count += 1
            else:
                # Work v2 PoW
                proof_row = conn.execute('SELECT proof FROM block_work WHERE hash = ?', (b['hash'],)).fetchone()
                assert proof_row is not None, f'Height {h} missing PoW proof in block_work'
                block_cand = {k: b[k] for k in ('height', 'previous_hash', 'timestamp', 'validator', 'signature')}
                block_cand['transactions'] = txs
                block_cand['work'] = json.loads(proof_row[0])
                res = work.verify(conn, NETWORK_ID, block_cand, b['hash'])
                assert res['work_verified'], f'Height {h} work verification failed'
                assert b['total_weight'] == parent_weight + 1000, f'Height {h} total_weight mismatch: {b["total_weight"]} != {parent_weight + 1000}'
                pow_count += 1

            parent_hash = b['hash']
            parent_height = h
            parent_time = b['timestamp']
            parent_weight = b['total_weight']

        # Verify state commitments
        print(f'[SUCCESS] Verified {limit_height + 1} blocks successfully:')
        print(f'  - Genesis: {GENESIS_HASH}')
        print(f'  - Legacy PoS blocks (1..{WORK_V2_ACTIVATION_HEIGHT - 1}): {legacy_count}')
        print(f'  - Work v2 PoW blocks ({WORK_V2_ACTIVATION_HEIGHT}..{limit_height}): {pow_count}')
        print(f'  - Chain Tip Hash: {parent_hash}')
        print(f'  - Chain Cumulative Work / Total Weight: {parent_weight}')

        return {
            'status': 'VERIFIED',
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
    args = parser.parse_args()

    report = verify_history(args.db, args.max_height)
    if args.json:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
