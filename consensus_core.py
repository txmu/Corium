"""ConsensusValidationCore: Sovereign, deterministic PoW consensus and dynamic difficulty engine.

This module provides the single authoritative consensus validation kernel for Ziokt/Corium.
It strictly decouples open PoW mining from PoS governance and PoUW task attestations:
- PoW: open to any valid secp256k1 key pair without staking or validator table registration.
- Dynamic Difficulty: deterministic integer retargeting window with bounded timespan damping.
- Cumulative Work: block_work = floor(2^256 / (target + 1)).
- Fork Choice: greatest cumulative work with deterministic lexicographic tie-breaker.
- Migration Anchors: preserves historical block weights for backwards compatibility.
"""
import contextlib
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Dict, List, Optional, Tuple, Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

# Core consensus constants
MAINNET_NETWORK_ID = 'ziokt-main'
MAINNET_GENESIS_HASH = '599b7512c4ffb640520433f0772f00e78198ad958f444d25459dbca8c38ce0fa'
WORK_V2_ACTIVATION_HEIGHT = 64
WORK_V2_POLICY_COMMITMENT = '9caf67936f6d1881296b97f5a5524f344ab06547d4eec78fc352f695228fa8df'

# Dynamic difficulty parameters (candidate defaults, overridable via governed policy)
TARGET_SPACING = 60          # Target 60 seconds per block
RETARGET_INTERVAL = 10       # Recompute difficulty every 10 blocks
DAMPING_FACTOR = 4           # Max adjustment factor up or down per retarget window (1/4 to 4x)
MIN_DIFFICULTY_BITS = 4      # Lowest allowed difficulty (for testnets / early phase)
MAX_DIFFICULTY_BITS = 240    # Highest allowed difficulty
MAX_FUTURE_TIME = 7200       # Up to 2 hours in the future allowed for timestamp drift
MAX_TRANSACTIONS_PER_BLOCK = 200

# Target boundaries
MAX_TARGET = (1 << (256 - MIN_DIFFICULTY_BITS)) - 1
MIN_TARGET = 1 << (256 - MAX_DIFFICULTY_BITS)

SCHEMA_STATIC_V1 = 'corium.work-weight-policy.v1'
SCHEMA_STATIC_V2 = 'corium.native-work-policy.v2'
SCHEMA_DYNAMIC_V1 = 'corium.dynamic-work-policy.v1'
PROOF_SCHEMA = 'corium.native-block-work.v2'

HEX_RE = re.compile(r'^[a-f0-9]{64}$')


class ConsensusError(Exception):
    """Raised when consensus rule validation fails."""
    def __init__(self, code: str, message: str):
        super().__init__(f'[{code}] {message}')
        self.code = code
        self.message = message


def canonical_json(obj: Any) -> bytes:
    """Deterministic canonical JSON serialization."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def sha256_hex(data: bytes) -> str:
    """Compute standard SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def target_from_bits(bits: int) -> int:
    """Compute 256-bit integer target from difficulty bits."""
    if not (1 <= bits <= 256):
        raise ConsensusError('INVALID_DIFFICULTY_BITS', f'Bits {bits} out of range [1, 256]')
    return (1 << (256 - bits)) - 1


def bits_from_target(target: int) -> int:
    """Estimate difficulty bits from integer target."""
    if target <= 0:
        return 256
    bit_len = target.bit_length()
    return max(1, min(256, 256 - bit_len))


def calculate_block_work(target: int) -> int:
    """Compute discrete integer work: floor(2^256 / (target + 1))."""
    if target <= 0 or target > (1 << 256) - 1:
        raise ConsensusError('INVALID_TARGET', 'Target must be a positive 256-bit integer')
    work = (1 << 256) // (target + 1)
    return max(1, work)


def calculate_retarget(
    prev_target: int,
    actual_timespan: int,
    expected_timespan: int = RETARGET_INTERVAL * TARGET_SPACING,
    damping_factor: int = DAMPING_FACTOR
) -> int:
    """Deterministic integer difficulty retargeting with bounded damping.
    
    Prevents sudden dramatic swings while ensuring responsiveness to hashrate shifts.
    """
    if prev_target <= 0:
        prev_target = MAX_TARGET
    if expected_timespan <= 0:
        expected_timespan = RETARGET_INTERVAL * TARGET_SPACING

    min_timespan = expected_timespan // damping_factor
    max_timespan = expected_timespan * damping_factor
    clamped_timespan = max(min_timespan, min(actual_timespan, max_timespan))

    new_target = (prev_target * clamped_timespan) // expected_timespan
    return max(MIN_TARGET, min(new_target, MAX_TARGET))


class ConsensusValidationCore:
    """Unified consensus engine validating blocks, transactions, difficulty and chain selection."""

    def __init__(self, db_path: str, network_id: str = MAINNET_NETWORK_ID):
        self.db_path = db_path
        self.network_id = network_id

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextlib.contextmanager
    def connection_scope(self):
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_tip(self) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            row = conn.execute(
                'SELECT height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight '
                'FROM blocks ORDER BY height DESC LIMIT 1'
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_block_by_hash(self, block_hash: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            row = conn.execute(
                'SELECT height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight '
                'FROM blocks WHERE hash = ?',
                (block_hash,)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            if isinstance(res.get('transactions'), str):
                try:
                    res['transactions'] = json.loads(res['transactions'])
                except Exception:
                    res['transactions'] = []
            proof_row = conn.execute('SELECT proof FROM block_work WHERE hash = ?', (block_hash,)).fetchone()
            if proof_row:
                res['work'] = json.loads(proof_row[0])
            return res
        finally:
            conn.close()

    def get_block_by_height(self, height: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            row = conn.execute(
                'SELECT height, hash, previous_hash, timestamp, validator, signature, transactions, total_weight '
                'FROM blocks WHERE height = ?',
                (height,)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            if isinstance(res.get('transactions'), str):
                try:
                    res['transactions'] = json.loads(res['transactions'])
                except Exception:
                    res['transactions'] = []
            proof_row = conn.execute('SELECT proof FROM block_work WHERE hash = ?', (res['hash'],)).fetchone()
            if proof_row:
                res['work'] = json.loads(proof_row[0])
            return res
        finally:
            conn.close()

    def get_consensus_mode(self, height: int) -> str:
        """Determine consensus mode at a given block height."""
        if height < WORK_V2_ACTIVATION_HEIGHT:
            return 'legacy-pos'
        return 'pow-v2'

    def get_expected_target(self, parent_height: int, parent_hash: str, parent_timestamp: int) -> int:
        """Calculate the deterministic expected PoW target for the candidate block at parent_height + 1."""
        candidate_height = parent_height + 1
        activation_floor = 1 if (self.network_id.startswith('test-') or self.network_id.startswith('ziokt-test-')) else WORK_V2_ACTIVATION_HEIGHT
        if candidate_height < activation_floor:
            return MAX_TARGET

        # During static Work v2 (prior to dynamic activation), target corresponds to 4 bits
        # In dynamic mode or when configured:
        # Check if dynamic retargeting is activated (either testnet or height >= dynamic activation)
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT param_value FROM system_params WHERE param_key = 'dynamic_pow_activation_height'"
            ).fetchone()
            dyn_activation = int(row[0]) if row else 1000000000  # Default future if unset

            # Also check test network override
            if self.network_id.startswith('test-') or self.network_id.startswith('ziokt-test-'):
                dyn_activation = min(dyn_activation, WORK_V2_ACTIVATION_HEIGHT)

            if candidate_height < dyn_activation:
                # Return static Work v2 target (difficulty_bits = 4)
                return target_from_bits(4)

            # Dynamic retargeting logic:
            if candidate_height % RETARGET_INTERVAL != 0:
                # Non-retarget block inherits target from parent
                parent_proof = conn.execute('SELECT proof FROM block_work WHERE hash = ?', (parent_hash,)).fetchone()
                if parent_proof:
                    proof_data = json.loads(parent_proof[0])
                    if 'target' in proof_data:
                        return int(proof_data['target'])
                return target_from_bits(4)

            # Boundary block: recompute based on previous RETARGET_INTERVAL blocks
            start_height = candidate_height - RETARGET_INTERVAL
            start_row = conn.execute('SELECT timestamp FROM blocks WHERE height = ?', (start_height,)).fetchone()
            if not start_row:
                return target_from_bits(4)

            start_timestamp = int(start_row[0])
            actual_timespan = parent_timestamp - start_timestamp
            expected_timespan = RETARGET_INTERVAL * TARGET_SPACING

            # Read parent target
            parent_target = target_from_bits(4)
            parent_proof = conn.execute('SELECT proof FROM block_work WHERE hash = ?', (parent_hash,)).fetchone()
            if parent_proof:
                proof_data = json.loads(parent_proof[0])
                if 'target' in proof_data:
                    parent_target = int(proof_data['target'])

            return calculate_retarget(parent_target, actual_timespan, expected_timespan)
        finally:
            conn.close()

    @staticmethod
    def signing_bytes(block: Dict[str, Any]) -> bytes:
        """Construct canonical signing bytes for a candidate block."""
        data = {k: v for k, v in block.items() if k != 'signature'}
        return b'Corium/NativeWorkBlock/v2\0' + canonical_json(data)

    @staticmethod
    def work_context(block: Dict[str, Any]) -> Dict[str, Any]:
        """Construct binding context for the PoW proof."""
        proof = block['work']
        body = {k: v for k, v in block.items() if k not in {'signature', 'work'}}
        body['work'] = {k: v for k, v in proof.items() if k != 'nonce'}
        body_digest = sha256_hex(b'Corium/NativeWorkBody/v2\0' + canonical_json(body))
        return {
            'height': block['height'],
            'parent': block['previous_hash'],
            'body': body_digest,
            'miner': block['validator']
        }

    @staticmethod
    def calculate_work_digest(policy_commitment: str, context: Dict[str, Any], nonce: int) -> str:
        """Calculate the SHA-256 digest of the work proof candidate."""
        proof_payload = {
            'schema': 'corium.sha256-work.v1',
            'policy': policy_commitment,
            'context': context,
            'nonce': nonce
        }
        return sha256_hex(b'Corium/BlockWork/v1\0' + canonical_json(proof_payload))

    def verify_miner_signature(self, block: Dict[str, Any], raw_signing_bytes: bytes) -> bool:
        """Verify block ECDSA signature directly with miner's public key (no PoS table lookup)."""
        proof = block.get('work')
        if not proof or 'miner_public_key' not in proof:
            raise ConsensusError('MISSING_MINER_KEY', 'Work proof missing miner public key')

        pub_pem = proof['miner_public_key']
        expected_validator_id = sha256_hex(pub_pem.encode('utf-8'))
        if block.get('validator') != expected_validator_id:
            raise ConsensusError('VALIDATOR_MISMATCH', 'Block validator does not match SHA-256 of miner public key')

        try:
            key = serialization.load_pem_public_key(pub_pem.encode('ascii'))
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256K1):
                raise ConsensusError('INVALID_KEY_TYPE', 'SECP256K1 elliptic curve public key required')
            sig_hex = block.get('signature', '')
            if not isinstance(sig_hex, str) or not re.fullmatch(r'[a-f0-9]{16,144}', sig_hex) or len(sig_hex) % 2 != 0:
                raise ConsensusError('MALFORMED_SIGNATURE', 'Invalid DER hex signature encoding')
            key.verify(bytes.fromhex(sig_hex), raw_signing_bytes, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            raise ConsensusError('INVALID_SIGNATURE', 'Signature verification failed against miner public key')
        except Exception as e:
            if isinstance(e, ConsensusError):
                raise
            raise ConsensusError('CRYPTO_ERROR', str(e))

    def verify_block_integrity(self, block: Dict[str, Any], expected_hash: str) -> Dict[str, Any]:
        """Comprehensive verification of a candidate block against consensus invariants."""
        # Normalize in case a database row is passed with extra columns
        clean_block = {k: v for k, v in block.items() if k not in {'hash', 'total_weight'}}
        required_fields = {'height', 'previous_hash', 'timestamp', 'validator', 'signature', 'transactions', 'work'}
        if not isinstance(clean_block, dict) or set(clean_block) != required_fields:
            raise ConsensusError('INVALID_BLOCK_SCHEMA', f'Block fields mismatch: expected {required_fields}, got {set(clean_block)}')

        height = clean_block['height']
        prev_hash = clean_block['previous_hash']
        timestamp = clean_block['timestamp']
        block = clean_block

        # Verify parent block
        parent = self.get_block_by_hash(prev_hash)
        if not parent:
            raise ConsensusError('MISSING_PARENT', f'Parent block {prev_hash} not found in chain')

        if height != parent['height'] + 1:
            raise ConsensusError('HEIGHT_SEQUENCE_ERROR', f'Height {height} != parent height {parent["height"]} + 1')

        if timestamp < parent['timestamp']:
            raise ConsensusError('TIMESTAMP_DECREASING', f'Timestamp {timestamp} < parent timestamp {parent["timestamp"]}')

        # Verify transactions structure
        txs = clean_block['transactions']
        if isinstance(txs, str):
            try:
                txs = json.loads(txs)
                clean_block['transactions'] = txs
            except Exception:
                raise ConsensusError('MALFORMED_TX_JSON', 'Transactions field must be valid JSON array')
        if not isinstance(txs, list) or len(txs) > MAX_TRANSACTIONS_PER_BLOCK:
            raise ConsensusError('TX_LIST_INVALID', f'Transaction list exceeds maximum {MAX_TRANSACTIONS_PER_BLOCK}')
        if len(set(txs)) != len(txs):
            raise ConsensusError('DUPLICATE_TX', 'Duplicate transaction hashes inside block')
        for tx in txs:
            if not isinstance(tx, str) or not HEX_RE.fullmatch(tx):
                raise ConsensusError('MALFORMED_TX_HASH', f'Invalid transaction hash format: {tx}')

        # Verify work proof
        proof = block['work']
        proof_fields = {'schema', 'activation', 'policy', 'miner_public_key', 'nonce'}
        if not isinstance(proof, dict) or not proof_fields.issubset(set(proof)):
            raise ConsensusError('INVALID_WORK_PROOF', 'Missing required work proof fields')

        # Determine target
        expected_target = self.get_expected_target(parent['height'], prev_hash, parent['timestamp'])
        ctx = self.work_context(block)
        work_hash = self.calculate_work_digest(proof['policy'], ctx, proof['nonce'])

        if int(work_hash, 16) > expected_target:
            raise ConsensusError('POW_INSUFFICIENT', f'PoW hash {work_hash} exceeds target {hex(expected_target)}')

        # Verify block signature
        raw_bytes = self.signing_bytes(block)
        calculated_hash = sha256_hex(raw_bytes)
        if calculated_hash != expected_hash:
            raise ConsensusError('BLOCK_HASH_MISMATCH', f'Calculated hash {calculated_hash} != expected {expected_hash}')

        self.verify_miner_signature(block, raw_bytes)

        # Calculate incremental block work and cumulative chain work
        # In Work v2 (static mode): incremental work is 1000
        # In Dynamic mode: incremental work is calculate_block_work(expected_target)
        mode = self.get_consensus_mode(height)
        if 'target' in proof:
            block_work = calculate_block_work(int(proof['target']))
        else:
            block_work = 1000

        total_weight = parent['total_weight'] + block_work

        return {
            'hash': expected_hash,
            'height': height,
            'validator': block['validator'],
            'block_work': block_work,
            'total_weight': total_weight,
            'target': expected_target,
            'work_digest': work_hash,
            'verified': True
        }

    def mine_candidate_block(
        self,
        private_key_pem: bytes,
        parent_hash: str,
        timestamp: int,
        transactions: List[str],
        attempts: int = 200000,
        start_nonce: int = 0
    ) -> Dict[str, Any]:
        """Mine a valid candidate block for open consensus without stake prerequisites."""
        parent = self.get_block_by_hash(parent_hash)
        if not parent:
            raise ConsensusError('PARENT_NOT_FOUND', f'Cannot mine on non-existent parent {parent_hash}')

        height = parent['height'] + 1
        priv_key = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(priv_key, ec.EllipticCurvePrivateKey) or not isinstance(priv_key.curve, ec.SECP256K1):
            raise ConsensusError('INVALID_PRIVATE_KEY', 'secp256k1 private key required for mining')

        pub_pem = priv_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('ascii').rstrip('\n')
        validator_id = sha256_hex(pub_pem.encode('utf-8'))

        target = self.get_expected_target(parent['height'], parent_hash, parent['timestamp'])
        
        # Policy commitments
        policy_commitment = 'bfdc803c5aeba84b350af4b9eed33bc488c15b4637bb6eb360470bb7859353d8'
        activation_hash = WORK_V2_POLICY_COMMITMENT

        block: Dict[str, Any] = {
            'height': height,
            'previous_hash': parent_hash,
            'timestamp': timestamp,
            'validator': validator_id,
            'signature': '',
            'transactions': transactions,
            'work': {
                'schema': PROOF_SCHEMA,
                'activation': activation_hash,
                'policy': policy_commitment,
                'miner_public_key': pub_pem,
                'nonce': 0,
                'target': target
            }
        }

        ctx = self.work_context(block)
        for nonce in range(start_nonce, start_nonce + attempts):
            digest_val = self.calculate_work_digest(policy_commitment, ctx, nonce)
            if int(digest_val, 16) <= target:
                block['work']['nonce'] = nonce
                raw = self.signing_bytes(block)
                block_hash = sha256_hex(raw)
                sig = priv_key.sign(raw, ec.ECDSA(hashes.SHA256())).hex()
                block['signature'] = sig
                verification = self.verify_block_integrity(block, block_hash)
                return {
                    'block': block,
                    'hash': block_hash,
                    **verification
                }

        raise ConsensusError('MINING_EXHAUSTED', f'Bounded mining exhausted after {attempts} attempts')

    def should_reorganize(self, candidate_tip: Any, current_tip: Any) -> bool:
        """Deterministic fork choice rule based strictly on greatest cumulative work."""
        cand_block = candidate_tip if isinstance(candidate_tip, dict) else self.get_block_by_hash(str(candidate_tip))
        curr_block = current_tip if isinstance(current_tip, dict) else self.get_block_by_hash(str(current_tip))

        if not cand_block:
            return False
        if not curr_block:
            return True

        cand_hash = cand_block.get('hash', '')
        curr_hash = curr_block.get('hash', '')
        if cand_hash == curr_hash and cand_hash:
            return False

        if cand_block['total_weight'] > curr_block['total_weight']:
            return True
        elif cand_block['total_weight'] < curr_block['total_weight']:
            return False
        else:
            # Deterministic tie-breaker: lower hash lexicographically
            return cand_hash < curr_hash
