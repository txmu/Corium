# Governed OpenCI attested bounties v1 (Production Consensus & Multi-Node Verified)

The native `compute/openci-attested:1` engine reuses the real signed
`propose_new_compute_engine`, validator voting, 100-block voting window and
10-block enactment delay. The signed proposal includes `openci_policy`; its hash
and the exact generated verifier source hash bind all subsequent claims. A
policy explicitly names its network/genesis, admission heights, up to 16 bounties,
fixed recipients, anchored sources/programs and 2–8 approved witness keys/domains.
Eligible networks include production networks (`ziokt-main`, `mainnet`) and testnets
under explicit on-chain governance approval.

Worker statements retain the existing `OpenCI/worker-receipt/v1` signature format.
Full task descriptions bind those signatures to the approved argv, pinned image,
source, outputs and resource limits. The last argv element is a native claim
context token; for Python `-c` or shell `-c`, supply it as a positional argument.
Each quorum needs distinct approved identities, keys and declared failure domains,
including a trusted witness, with the same pipeline and artifact digest. Source,
recipient, policy, task or output substitution fails closed. Validators perform
bounded signature/JSON checks; they never execute remote code, OCI or compilers.

This is an explicitly governed trust model. Keys/domains are governance claims,
with cryptographic verification of witness signatures and failure domains.
Ordinary successful CI is ineligible without a prior approved bounty, matching
quorum and native transaction.

`submit_math_proof` is fully checked during native transaction validation and
state application. A valid proof becomes native pending state. After its existing
10-block challenge window, settlement atomically writes the exact proof hash to
`completed_compute_tasks` and credits `100 * reward_weight` to
`contribution_scores`. Overflow, challenge, wrong recipient and double redemption
fail. Rejected spurious challenges do not permanently withhold an eligible bounty.
Contribution scores reflect earned computational contributions under governance policies.

`spec/openci_consensus.py` in Ziokt is the canonical generator input; Corium keeps
an identical standalone `openci_consensus.py` and a generated self-contained
monolith copy with its canonical source digest. Do not mutate an activated v1
verifier in place: deploy a distinct governed verifier/version and preserve
historical verification behavior for replay.

Tests distinguish cryptographic fixture receipts from real OCI execution.
Local units and admission tests use real native schemas/keys/signatures and
native proposal/vote mining. CI executes actual OCI tasks, earns proposal
eligibility, mines all blocks through governance and settlement, and independently
Phoenix-rebuilds signed history across multiple nodes. Production activation has
completed full validation for v1.0.
