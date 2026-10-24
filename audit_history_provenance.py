#!/usr/bin/env python3
"""Read-only historical evidence audit; never repairs or blesses a chain.

Genesis validator keys are explicit inputs. The legacy block hash commits only
the timestamp/header, not the complete genesis allocation or validator set.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def audit(db_path, genesis_path, activation_height=64):
    genesis=json.loads(Path(genesis_path).read_text())
    keys={hashlib.sha256(v['public_key'].rstrip('\n').encode()).hexdigest():v['public_key']
          for v in genesis['genesis_validators']}
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        blocks=db.execute('SELECT * FROM blocks ORDER BY height').fetchall()
        memberships={row['height']:json.loads(row['transactions']) for row in blocks}
        errors=[]
        for row in blocks:
            if not isinstance(memberships[row['height']],list):
                raise ValueError('Malformed canonical transaction list')
        off_chain=[]
        for row in db.execute('SELECT hash,type,block_height FROM transactions WHERE block_height IS NOT NULL'):
            if memberships.get(row['block_height'],[]).count(row['hash'])!=1:
                off_chain.append({'transaction':row['hash'],'type':row['type'],'claimed_height':row['block_height']})
        active=[]
        for row in db.execute("SELECT e.engine_id,t.block_height FROM compute_engines e JOIN transactions t ON t.hash=e.engine_id WHERE e.pkg_id='consensus/work-weight:2' AND e.is_active=1"):
            committed=memberships.get(row['block_height'],[]).count(row['engine_id'])==1
            active.append({'proposal':row['engine_id'],'claimed_height':row['block_height'],'canonically_included':committed})
            if not committed:
                errors.append({'code':'WORK_GOVERNANCE_NOT_COMMITTED','proposal':row['engine_id'],
                               'claimed_height':row['block_height'],'first_unverified_height':activation_height})
        checked=0
        parent=None
        for row in blocks:
            if row['height']==0:
                parent=row
                continue
            if row['height']>=activation_height:
                break
            try:
                if parent is None or row['height']!=parent['height']+1 or row['previous_hash']!=parent['hash']:
                    raise ValueError('broken legacy ancestry')
                body={k:row[k] for k in ('height','previous_hash','timestamp')}
                body['transactions']=memberships[row['height']]
                raw=json.dumps(body,separators=(',',':'),ensure_ascii=False).encode()
                if hashlib.sha256(raw).hexdigest()!=row['hash']:
                    raise ValueError('legacy block hash mismatch')
                key=serialization.load_pem_public_key(keys[row['validator']].encode())
                if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256K1):
                    raise ValueError('legacy validator key must be secp256k1')
                key.verify(bytes.fromhex(row['signature']),raw,ec.ECDSA(hashes.SHA256()))
                checked+=1
            except Exception as exc:
                errors.append({'code':'LEGACY_HEADER_OR_SIGNATURE_INVALID','height':row['height'],
                               'detail':type(exc).__name__})
                break
            parent=row
        auxiliary=db.execute('SELECT COUNT(*) FROM block_work w JOIN blocks b ON b.hash=w.hash WHERE b.height<?',(activation_height,)).fetchone()[0]
    return {'schema':'corium.history-provenance-audit.v1',
            'status':'REJECTED' if errors or off_chain else 'SCOPED_CHECKS_PASSED',
            'full_history_verified':False,'legacy_headers_and_signatures_checked':checked,
            'genesis_config_sha256':hashlib.sha256(Path(genesis_path).read_bytes()).hexdigest(),
            'genesis_state_committed_by_legacy_header':False,
            'genesis_validator_input':'explicit configuration; allocation/registry not bound by legacy block hash',
            'off_chain_confirmed_transactions':off_chain,'active_work_policies':active,
            'preactivation_auxiliary_work_records':auxiliary,'errors':errors,
            'transaction_execution_and_state_commitments':'requires native/independent replay',
            'source_databases_modified':False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('--genesis',required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=audit(args.db,args.genesis)
    raw=json.dumps(report,indent=2)+'\n'
    if args.output:
        args.output.write_text(raw)
    print(raw,end='')
    return 1 if report['status']=='REJECTED' else 0


if __name__=='__main__':
    raise SystemExit(main())
