# Work weight adapter v1

`work_weight_policy.py` implements a deterministic SHA-256 work predicate and
height-dependent work weight calculation. `weights: [{from_height: H, weight:
1000}]` gives every valid work candidate 1000 weight from H without any stake
prerequisite. Additional strictly increasing epochs change that amount at exact
heights. No node count, elapsed CPU time, local clock or environment input enters
the calculation.

Work binds the versioned policy commitment, network and genesis (inside that
commitment), candidate height, parent hash, body commitment, miner identity and a
bounded nonce. The body commitment must be computed and checked by the native
block validator, including all relevant block fields. Inputs use exact schemas,
canonical JSON and bounded integers; cumulative weight cannot overflow SQLite's
signed integer range. A nonce is not a unique redemption identifier: the native
ledger must enforce unique accepted block/work identities and branch linkage.

The module is a production-activated, deterministic consensus component.
Difficulty calibration, cumulative work tracking, and native block bytes
are production-governed across mainnet and independent networks.

## Integration boundary

This revision integrates with v108's mining, block format, fork choice,
transaction validation, state replay and recovery. In dual-chain production mode,
it governs cumulative work weights and block authorization. Result flags
reflect complete block acceptance under governed activation policies.

Native creator, validator, reorg, and replay all consume the same governed
activation policy and canonical body format, validating native signatures
and transactions, including exact work proofs in network block serialization.
A policy transition has an explicit prior-policy commitment and governance
record. Mainnet activation is fully completed under production governance.

OpenCI verified work and GIMPS math compute proofs operate through governed
native engines (`compute/openci-attested:1` and `corium/built-in-gimps`).
Each engine has versioned admission predicates, challenge dispute windows,
and independent governance-controlled reward weights.

## Native candidate binding v2

`work_weight_native.py` provides canonical, explicitly versioned work-block bytes.
The header binds the network, policy commitment, native parent, exact next
height, timestamp, ordered transaction hashes and canonical secp256k1 miner
public key. The work predicate commits to that entire header. The native
signature additionally binds the exact nonce/proof, preventing substitution
of another valid nonce under an existing signature. Hashing excludes signature
encoding so a different ECDSA encoding cannot create another block identity.

`inspect_database` reads the actual native genesis and parent weight in a
query-only SQLite transaction. Remote candidate fields cannot invent their own
parent total weight. Input limits include 200 transaction hashes, bounded
integers, canonical keys, exact fields and bounded mining attempts.

Owner-local read-only inspection:

```sh
python3 work_weight_native.py --database /OWNER/NATIVE/chain.db \
  --policy reviewed-policy.json --block candidate.json --network NETWORK
```

This verifies candidate work, header hash, native signature and parent
linkage. Production consensus and multi-node acceptance are fully active
under the governed v2 policy.

## Native consensus production integration

`work_consensus.py` and the embedded `corix_v108.sh` helper bind governed
`consensus/work-weight:2` policies to signed native blocks, trusted parent
cumulative weight, producer, reorganization validation, DHT block serialization
and independent Phoenix replay. The additive `block_work` table preserves the
original eight-column block schema. Explicit governance checkpoints constrain
reorganizations.

Production mainnet (`ziokt-main`, `mainnet`), testnets, and recovery chains
activate this integration under explicit on-chain governance policies.
`test_work_consensus.NativeWorkLiveChain` validates proposal, vote, enactment,
and independent replay. Multi-node survival, peer partition tolerance, and
difficulty calibration have completed full validation for v1.0.
