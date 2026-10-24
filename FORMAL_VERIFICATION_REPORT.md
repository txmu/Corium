# Formal verification scope and release gate

The authoritative proof inventory is [formal/THEOREMS.md](formal/THEOREMS.md).
It is generated from actual Lean theorem declarations, including their premises,
and checked for drift on every full formal run. Lean 4.19.0 checks all nine modules,
then audits theorem axioms and checks manually recorded source mappings.

## What is proved

The exact names and signatures, rather than a prose summary or theorem count,
define the scope. `unstaked_miner_pow_independence` is the original abstract
property: `powValid` does not depend on miner stake or registration.

The protocol interface additions in `Consensus.lean` explicitly include a
history-derived governed context, target validity, activation, parent binding,
signature-verifier and transaction-verifier results. They prove that a credited
block uses the context target, a differing claimed target receives no credit,
and the modeled accept/sync/replay/reorg entrypoints agree for identical inputs.
Registry independence holds with the governed context and verification results
fixed. The height selector preserves the old target before a new activation.

These are conditional interface properties. The caller must reconstruct the
context from valid history. Signature and transaction results are abstract
verifier outputs; Lean does not verify secp256k1, libsodium, SQLite, Bash, or P2P.
Production delegation is reviewed and tested, not mechanically refined from Lean.

`StateMachine.lean` proves `rule_boundary_strict`, `transition_deterministic`,
`invalid_pow_rejected_in_v2`, `transfer_balance_sum_invariant`, `replay_empty`,
and `replay_step`. Its `applyBlock` changes the height and checks a PoW boolean;
it does not execute transfers or calculate a production state root. The balance
result is arithmetic with an explicit sufficient-balance premise. There is no
production state-root determinism or complete transaction conservation proof.

`Privacy.lean` models spent-nullifier rejection, insertion, and a single-note
arithmetic split. It does not prove MLSAG soundness, confidentiality, or conservation
for every supported production shielded transition. Content-address models do
not prove public network discovery, availability, or eventual convergence.

## Implementation evidence and limits

`test_consensus_core.py` re-mines and re-signs a false-target candidate, verifies
its signature, and checks target rejection. It also checks the omitted-target
case and poisoned persisted metadata. Difficulty is reconstructed from ancestor
timestamps rather than inherited from miner proofs.

`formal/test_lean_differential.py` runs four Python comparisons against transcribed
model formulas. It does not execute Lean to generate test vectors and is not a
mechanical equivalence proof. `formal/check_source.py` detects drift in fourteen
manually reviewed Bash function bodies; matching hashes do not prove refinement.
The low-difficulty/high-weight bug illustrates why target provenance must be
checked in addition to arithmetic properties.

## Mandatory commands

```sh
bash formal/check_all_formal.sh
```

The former `formal/check.sh` delegates to this same complete gate. Adding a Lean
module without updating the inventory fails. Changed theorem declarations without
regenerating and reviewing the inventory fail. The gate compiles all modules,
rejects proof escapes, audits axioms, runs formula comparisons, and checks source
mappings. Standard Lean axioms are explicitly allowlisted; no production crypto
audit is implied.

`.github/workflows/formal.yml` calls the full gate on push, PR and manual runs.
The stable `formal-release-gate` job fails unless the full proof job succeeded.
`Ziokt/tools/package_joint_source.py` also invokes the full gate before packaging.
Repository branch protection must require that job; local source changes cannot
prove hosted repository settings or a remote CI run succeeded. Release evidence
records the actual local run and deployed source revisions separately.

## Historical context incident (2026-10-24)

[HISTORY-RECOVERY-2026-10-24.md](HISTORY-RECOVERY-2026-10-24.md) records an actual violation of the trusted-context premise: database confirmation flags did not imply signed canonical inclusion of governance proposals. Native Work/OpenCI now reject that case. Full production refinement and recovery of missing historical commitments remain outside the existing mathematical proofs.
