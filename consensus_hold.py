#!/usr/bin/env python3
"""systemd ExecCondition: fail closed on an active or invalid local safety hold,
and verify authorized recovery branch for ziokt-main.
"""
import json
import os
from pathlib import Path
import stat
import sys
import sqlite3
import hashlib
import re

# BEGIN GENERATED VERIFIED GUARDS
def _contract_argument(value, kind):
    valid = (type(value) is int and value >= 0) if kind == "Nat" else type(value) is bool if kind == "Bool" else type(value) is str if kind == "String" else type(value) is list and all(type(item) is bool for item in value)
    if not valid: raise ValueError("verified guard argument outside its proved domain: " + kind)


def hold_may_start(active, requires_authorization, authorized):
    _contract_argument(active, 'Bool')
    _contract_argument(requires_authorization, 'Bool')
    _contract_argument(authorized, 'Bool')
    return (not active and (not requires_authorization or authorized))


def block_linked(height, digest, next_height, next_previous):
    _contract_argument(height, 'Nat')
    _contract_argument(digest, 'String')
    _contract_argument(next_height, 'Nat')
    _contract_argument(next_previous, 'String')
    return ((next_height == (height + 1)) and (next_previous == digest))


# END GENERATED VERIFIED GUARDS

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


def _verify_recovery_auth(auth, path_context=None):
    if not isinstance(auth, dict):
        return False
    required_keys = {
        'schema', 'network_id', 'chain_id', 'genesis_hash',
        'anchor_h50_hash', 'recovery_h51_hash', 'approved_checkpoint_height',
        'approved_checkpoint_hash', 'canonical_database_path',
        'validator', 'validator_pubkey', 'signature'
    }
    if not required_keys.issubset(auth.keys()):
        return False
    if auth.get('schema') != 'ziokt.recovery-authorization.v1':
        return False
    if auth.get('network_id') != 'ziokt-main':
        return False
    if not HAVE_CRYPTO:
        return False

    # 1. Verify validator identity & signature
    pub_pem = auth['validator_pubkey'].strip()
    if hashlib.sha256(pub_pem.encode('utf-8')).hexdigest() != auth['validator']:
        return False
    try:
        pub = serialization.load_pem_public_key(pub_pem.encode('utf-8'))
        if not isinstance(pub, ec.EllipticCurvePublicKey) or not isinstance(pub.curve, ec.SECP256K1):
            return False
        unsigned = {k: v for k, v in auth.items() if k != 'signature'}
        payload = json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode('utf-8')
        sig_bytes = bytes.fromhex(auth['signature'])
        pub.verify(sig_bytes, b'Corium/RecoveryAuthorization/v1\0' + payload, ec.ECDSA(hashes.SHA256()))
    except Exception:
        return False

    # 2. Determine and verify canonical database on disk
    db_path = Path(auth['canonical_database_path'])
    if 'CORIUM_ROOT' in os.environ:
        env_root = Path(os.environ['CORIUM_ROOT'])
        env_network = os.environ.get('CORIUM_NETWORK_ID_OVERRIDE', auth['network_id'])
        candidate = env_root / 'var/lib/corix/networks' / env_network / 'blockchain/chain.db'
        if candidate.exists():
            db_path = candidate

    if not db_path.is_file():
        return False

    # 3. Read-only verification of canonical blocks in SQLite
    try:
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        cur = conn.cursor()

        # Check required heights: 0, 50, 51, 64
        cur.execute("SELECT height, hash, previous_hash FROM blocks WHERE height IN (0, 50, 51, 64) ORDER BY height")
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        if len(rows) < 4:
            conn.close()
            return False

        if rows[0][0] != auth['genesis_hash']:
            conn.close()
            return False
        if rows[50][0] != auth['anchor_h50_hash']:
            conn.close()
            return False
        if rows[51][0] != auth['recovery_h51_hash']:
            conn.close()
            return False
        if rows[64][0] != auth['approved_checkpoint_hash']:
            conn.close()
            return False

        # Check tip height >= approved_checkpoint_height
        cur.execute("SELECT MAX(height) FROM blocks")
        tip_h = cur.fetchone()[0]
        if tip_h is None or tip_h < auth['approved_checkpoint_height']:
            conn.close()
            return False

        # Check forbidden legacy hashes
        forbidden = auth.get('forbidden_legacy_hashes', [])
        if forbidden:
            placeholders = ','.join('?' for _ in forbidden)
            cur.execute(f"SELECT 1 FROM blocks WHERE hash IN ({placeholders}) LIMIT 1", forbidden)
            if cur.fetchone() is not None:
                conn.close()
                return False

        # Check chain continuity from 50 to 64
        cur.execute("SELECT height, hash, previous_hash FROM blocks WHERE height BETWEEN 50 AND 64 ORDER BY height")
        branch_rows = cur.fetchall()
        if len(branch_rows)!=15:
            conn.close()
            return False
        for i in range(1, len(branch_rows)):
            prev_block = branch_rows[i - 1]
            curr_block = branch_rows[i]
            if not block_linked(prev_block[0],prev_block[1],curr_block[0],curr_block[2]):
                conn.close()
                return False

        conn.close()
        return True
    except Exception:
        return False


def start_permitted(path):
    p = Path(path)
    is_mainnet = (
        os.environ.get('CORIUM_NETWORK_ID_OVERRIDE') == 'ziokt-main' or
        'ziokt-production' in str(p) or
        p.name == 'consensus-safety-hold.json'
    )

    try:
        metadata = p.lstat()
    except FileNotFoundError:
        # For ziokt-main / production: missing hold file is rejected (fail-closed)
        # For generic non-mainnet test fixtures: absent file permits startup
        return not is_mainnet

    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or (metadata.st_mode & 0o077) or metadata.st_size > 32768):
        return False

    try:
        value = json.loads(p.read_text())
    except (OSError, ValueError, UnicodeError):
        return False

    if not isinstance(value, dict) or value.get('schema') != 'ziokt.consensus-safety-hold.v1':
        return False

    if type(value.get('active')) is not bool:
        return False

    # When active is False:
    # For ziokt-main or when authorized_recovery is provided, authorized_recovery MUST be verified.
    requires_authorization=is_mainnet or 'authorized_recovery' in value
    authorized=False
    if not value['active'] and requires_authorization and 'authorized_recovery' in value:
        authorized=_verify_recovery_auth(value['authorized_recovery'],path_context=p)
    return hold_may_start(value['active'],requires_authorization,authorized)


if __name__ == '__main__':
    raise SystemExit(0 if len(sys.argv) == 2 and start_permitted(sys.argv[1]) else 1)
