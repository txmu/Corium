# Consensus and assurance remediation — 2026-10-23

## Work provenance

The standalone Python core now rejects a claimed target unless it is an exact
integer equal to the locally expected target. Missing target metadata receives
the same work as an explicit correct target. Both PoW verification and credited
work use that expected target. Difficulty is recomputed along parent hashes from
ancestor timestamps; persisted proof targets cannot poison subsequent difficulty.
Existing corrupted cumulative weights require validation/reconstruction before
fork comparison; this patch does not silently rewrite historical databases.

The native monolith uses its embedded `work_consensus.verify`, not the standalone
model. Its exact proof schema rejects target/weight fields. Its difficulty and
weight schedule come from the active governed policy. Mining calls `mine` and
`record`; peer acceptance calls `verify-file`; sync/announcement reorganization
calls `_blockchain_reorganize_to`, which calls `verify` and `record`; native state
replay calls the same `verify` and compares its returned cumulative weight.
These two protocol profiles retain different weight rules: the standalone dynamic
formula is not substituted for already-governed native historical weights.

The independent history checker now compares the weight returned by the governed
verifier instead of hard-coding 1000. Structural checks use explicit exceptions,
so Python optimization cannot disable them. Its result is `PARTIALLY_VERIFIED`,
with per-area coverage and trust dependencies. `--require-full` fails closed.
Optional `--native-root` reconstructs legacy signatures, transaction execution,
and governance using the existing native interpreter in scratch databases, and
reports a reconstructed semantic digest. This is not an independent interpreter
or proof of on-chain state-root commitments. The current independent checker does
not establish trustless joining; missing historical commitments cannot be invented.

## Privacy status

`ZS_MAINNET_ENABLED` preserves the existing functional enablement. `ZS_AUDITED`
is false because no third-party audit evidence is provided. Status separately
reports the project self-review, lack of third-party evidence, unverified mainnet
governance approval, and absence of complete cryptographic verification. Tests
cover enabled/disabled mainnet gates, cross-network rejection, invalid versions,
real ring proofs, and exact generated source alignment. Mainnet malformed input
rejection is tested without assuming the feature is disabled.

## Local survival scope

The lightweight four-process HTTP experiment gives each node its own SQLite DB
and private miner key. It stops the founder process, continues blocks on the two
survivors with an empty validator registry, and synchronizes a fourth genesis-only
node by revalidating received blocks. A re-mined and re-signed false-target block
is rejected; wire cumulative weight is ignored. This supports standalone empty
block history validation. Application transactions, public discovery, NAT traversal,
independent operators and production Corium wire interoperability are not covered.

## Formal and release evidence

[FORMAL_VERIFICATION_REPORT.md](FORMAL_VERIFICATION_REPORT.md) supersedes the
previous theorem summary. Exact declarations and premises are generated in
[formal/THEOREMS.md](formal/THEOREMS.md). Old and new entrypoints run the same
nine-module gate. The protocol interface model now includes governed context,
target provenance, activation, signature/transaction results and crediting.
Those results remain premises, not verified cryptographic implementations.

Local checks: 17 standalone consensus/process/history tests; 24 Ziokt privacy
tests; 6 targeted native privacy/work tests; 9 Gateway tests passed. The broader
native work/privacy/formal-alignment run completed 27 tests with one explicitly
skipped full live-chain fixture. Lean gate passed with all module and axiom checks,
14 manually mapped function hashes, and four Python formula comparisons. These
comparisons transcribe model formulas; they do not execute Lean-generated vectors.
Remote hosted CI status must be checked separately from local results.

Native scratch replay tests also reconstruct a real legacy transaction history,
reject corrupted block and transaction signatures, and exercise native governance
proposal/vote/mining/replay (two integration tests passed). The actual production
prefix through height 80 was additionally attempted and REJECTED at height 1:
all 63 pre-activation legacy blocks have auxiliary `block_work` rows, while native
legacy replay requires their absence. No source database records were deleted or
rewritten to make this pass. The supplied-database structural/PoW check passes
with partial coverage; it cannot override the native replay rejection. Production
history and governance provenance remain an explicit acceptance blocker.

Production evidence must identify source commits, frozen Python release, native
monolith hash, GUI build, and MCP tool-list/call observations. The Gateway assurance
page exposes scope separately from service health. A successful local model test
or an enabled privacy switch must never be displayed as full trustless validation.
