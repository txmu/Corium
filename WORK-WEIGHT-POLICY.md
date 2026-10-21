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
