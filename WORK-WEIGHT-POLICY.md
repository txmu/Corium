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

The module is an experimental new version, not an independently audited mining
protocol. Tests use a deliberately tiny difficulty to exercise the predicate;
they are not production difficulty calibration or meaningful contributed work.

## Integration boundary

This revision does **not** replace v108's stake lottery, mining, block format,
fork choice, transaction validation, state replay or recovery. It does not write
credits or stake. Result flags explicitly say `block_fully_validated: false`,
`ledger_modified: false`, `network_activated: false`. Calling this function is not
a complete block acceptance decision.

Before network activation, native creator/validator/reorg/replay must all consume
the same governed activation policy and canonical body format, validate native
signatures and transactions, and include the exact work proof in network block
serialization. A policy transition must have an explicit prior-policy commitment
and governance/upgrade record; rollback after activation requires a fork upgrade,
not deleting a local policy file. Mainnet activation has not occurred.

OpenCI verified work needs its own versioned admission predicate and native
engine governance; a successful SHA-256 nonce is not an OpenCI contribution.
The adapter currently rejects other proof schemas. Android relay contributions
require separately verified service receipts and cannot be represented by
invented compile proof data.

## Native candidate binding v2

`work_weight_native.py` adds canonical, explicitly versioned work-block bytes.
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

This verifies actual candidate work, header hash, native signature and parent
linkage. It does **not** validate transactions, establish governance approval,
grant proposal eligibility, accept a block, alter fork choice or reach finality.
The output explicitly preserves these separate states. Existing v108 blocks
and the mainnet consensus remain unchanged. The six native-parent tests include
real native transaction validation, original PoS mining and observing its parent
weight; they must not be called v2 consensus activation or multi-node acceptance.

## Native testnet integration under acceptance

`work_consensus.py` and the embedded `corix_v108.sh` helper now bind governed
`consensus/work-weight:2` policies to signed native blocks, trusted parent
cumulative weight, producer, reorganization validation, DHT block serialization
and independent Phoenix replay. The additive `block_work` table preserves the
original eight-column block schema. Explicit governance checkpoints constrain
reorganizations; they do not implement rolling finality. Difficulty is currently
fixed by the approved policy, not automatically adjusted.

Only `test-*` and `ziokt-test-*` networks can activate this integration. Presence
of code is not activation. `test_work_consensus.NativeWorkLiveChain` must pass
actual proposal/vote/enactment and independent replay on CI. Peer partition,
upgrade compatibility and difficulty calibration remain acceptance gates.
Production mainnet retains its original rules. This implementation does not
constitute completed mainnet migration or an anonymity guarantee.
