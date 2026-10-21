"""Versioned native-block binding for experimental SHA-256 work.

Verifies canonical bytes, parent linkage and the native secp256k1 identity. This
is a candidate verifier, not governance authorization or transaction admission.
The existing v108 block producer/fork choice are deliberately not replaced.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

from work_weight_policy import (
    PolicyError, MAX_HEIGHT, MAX_WEIGHT, PROOF, commitment, digest, encoded,
    integer, validate, verify_work, work_digest,
)

SCHEMA='corium.work-block.v2'
HEADER_FIELDS={'schema','network','policy','height','previous_hash','timestamp','transactions','miner_public_key'}
MAX_TRANSACTIONS=200


def public_key(value):
    if not isinstance(value,str) or len(value)>1024:
        raise PolicyError('WORK_MINER_KEY','Bounded native public key required')
    try:
        key=serialization.load_pem_public_key(value.encode('ascii'))
        if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256K1):raise ValueError()
        canonical=key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
        if canonical!=value:raise ValueError()
    except (ValueError,TypeError,UnicodeError):
        raise PolicyError('WORK_MINER_KEY','Canonical native secp256k1 public key required') from None
    return key


def parent_row(parent):
    if not isinstance(parent,dict) or set(parent)!={'height','hash','timestamp','total_weight'}:
        raise PolicyError('WORK_PARENT','Exact native parent fields required')
    integer(parent['height'],0,MAX_HEIGHT-1);digest(parent['hash'])
    integer(parent['timestamp'],0,2**63-1);integer(parent['total_weight'],0,MAX_WEIGHT)
    return parent


def header(policy, *, parent, timestamp, transactions, miner_public_key, network, genesis):
    policy=validate(policy);parent_row(parent)
    if policy['network']!=network or policy['genesis']!=genesis:
        raise PolicyError('WORK_CHAIN_MISMATCH','Native candidate belongs to another chain')
    integer(timestamp,parent['timestamp'],2**63-1)
    public_key(miner_public_key)
    if type(transactions) is not list or len(transactions)>MAX_TRANSACTIONS:
        raise PolicyError('WORK_TRANSACTIONS','At most 200 native transaction hashes required')
    for transaction in transactions:digest(transaction)
    if len(set(transactions))!=len(transactions):
        raise PolicyError('WORK_TRANSACTIONS','Duplicate transaction in candidate')
    return {'schema':SCHEMA,'network':network,'policy':commitment(policy),
            'height':parent['height']+1,'previous_hash':parent['hash'],
            'timestamp':timestamp,'transactions':list(transactions),'miner_public_key':miner_public_key}


def context(value):
    if type(value) is not dict or set(value)!=HEADER_FIELDS or value['schema']!=SCHEMA:
        raise PolicyError('WORK_BLOCK_SCHEMA','Exact versioned native header required')
    return {'height':value['height'],'parent':value['previous_hash'],
            'body':hashlib.sha256(b'Corium/WorkBlockBody/v2\0'+encoded(value)).hexdigest(),
            'miner':hashlib.sha256(value['miner_public_key'].encode()).hexdigest()}


def signing_bytes(value, proof):
    return b'Corium/WorkBlockSignature/v2\0'+encoded({'header':value,'work':proof})


def candidate(policy, *, parent, timestamp, transactions, private_key, network, genesis, attempts=10000, start_nonce=0):
    """Bounded actual work and ECDSA signing; no chain write or stake grant."""
    policy=validate(policy);parent=dict(parent_row(parent))
    integer(attempts,1,1000000);integer(start_nonce,0,2**64-1)
    if start_nonce>2**64-attempts:raise PolicyError('WORK_NONCE_RANGE','Nonce range overflows')
    if not isinstance(private_key,ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve,ec.SECP256K1):
        raise PolicyError('WORK_MINER_KEY','Native secp256k1 signing key required')
    miner=private_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
    value=header(policy,parent=parent,timestamp=timestamp,transactions=transactions,miner_public_key=miner,network=network,genesis=genesis)
    ctx=context(value)
    # Fail before doing work when the policy is not active or the weight overflows.
    from work_weight_policy import weight_at
    weight=weight_at(policy,value['height'],network=network,genesis=genesis)
    if parent['total_weight']>MAX_WEIGHT-weight:raise PolicyError('WORK_WEIGHT_OVERFLOW','Cumulative native weight overflows')
    for nonce in range(start_nonce,start_nonce+attempts):
        if int(work_digest(policy,ctx,nonce),16)>=(1<<(256-policy['difficulty_bits'])):continue
        proof={'schema':PROOF,'policy':value['policy'],'nonce':nonce}
        body=signing_bytes(value,proof)
        signature=private_key.sign(body,ec.ECDSA(hashes.SHA256())).hex()
        return {'header':value,'work':proof,'signature':signature,'hash':hashlib.sha256(body).hexdigest()}
    raise PolicyError('WORK_BUDGET_EXHAUSTED','No valid nonce in the bounded attempt range')


def verify_candidate(policy, block, *, parent, network, genesis):
    if type(block) is not dict or set(block)!={'header','work','signature','hash'}:
        raise PolicyError('WORK_BLOCK_SCHEMA','Exact native work block required')
    value=block['header']
    if type(value) is not dict or set(value)!=HEADER_FIELDS:raise PolicyError('WORK_BLOCK_SCHEMA','Exact native work header required')
    expected=header(policy,parent=parent,timestamp=value['timestamp'],transactions=value['transactions'],miner_public_key=value['miner_public_key'],network=network,genesis=genesis)
    if encoded(value)!=encoded(expected):raise PolicyError('WORK_PARENT','Height, parent, policy or chain binding mismatch')
    result=verify_work(policy,context(value),block['work'],network=network,genesis=genesis,parent_weight=parent['total_weight'])
    body=signing_bytes(value,block['work'])
    if digest(block['hash'])!=hashlib.sha256(body).hexdigest():raise PolicyError('WORK_BLOCK_HASH','Native candidate hash mismatch')
    signature=block['signature']
    if not isinstance(signature,str) or not re.fullmatch('[0-9a-f]{16,144}',signature) or len(signature)%2:
        raise PolicyError('WORK_BLOCK_SIGNATURE','Bounded DER ECDSA signature required')
    try:public_key(value['miner_public_key']).verify(bytes.fromhex(signature),body,ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature,ValueError):
        raise PolicyError('WORK_BLOCK_SIGNATURE','Native candidate signature rejected') from None
    return {**result,'schema':'corium.work-block-inspection.v2','hash':block['hash'],
            'canonical_header_verified':True,'native_signature_verified':True,'parent_link_verified':True,
            'proposal_eligibility':'not_assessed','transactions_validated':False,
            'governance_approved':'not_assessed','native_consensus_accepted':False,'finalized':False}


def inspect_database(database, policy, block, network):
    """Read the actual native genesis/parent; caller cannot invent parent weight."""
    path=Path(database)
    if path.is_symlink() or not path.is_file():raise PolicyError('WORK_DATABASE','Existing native database required')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        genesis=db.execute('SELECT hash FROM blocks WHERE height=0').fetchone()
        previous=block.get('header',{}).get('previous_hash') if type(block) is dict else None
        row=db.execute('SELECT height,hash,timestamp,total_weight FROM blocks WHERE hash=?',(previous,)).fetchone()
        if genesis is None or row is None:raise PolicyError('WORK_PARENT','Native genesis and parent must exist')
        result=verify_candidate(policy,block,parent=dict(zip(('height','hash','timestamp','total_weight'),row)),network=network,genesis=genesis[0])
        result['native_parent_observed']=True
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--block',type=Path,required=True)
    parser.add_argument('--network',required=True)
    args=parser.parse_args()
    def load(path):
        if path.is_symlink() or path.stat().st_size>65536:raise ValueError('bounded JSON document required')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('duplicate JSON key')
                value[key]=item
            return value
        return json.loads(path.read_bytes(),object_pairs_hook=unique)
    print(json.dumps(inspect_database(args.database,load(args.policy),load(args.block),args.network),sort_keys=True))
