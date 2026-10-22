# Governed OpenCI attested bounties v1 (testnet only)

The native `compute/openci-attested:1` engine reuses the real signed
`propose_new_compute_engine`, validator voting, 100-block voting window and
10-block enactment delay. The signed proposal includes `openci_policy`; its hash
and the exact generated verifier source hash bind all subsequent claims. A
policy explicitly names its network/genesis, admission heights, up to 16 bounties,
fixed recipients, anchored sources/programs and 2–8 approved witness keys/domains.
Only `test-*` / `ziokt-test-*` networks are admitted. No mainnet policy is enabled.

Worker statements retain the existing `OpenCI/worker-receipt/v1` signature format.
Full task descriptions bind those signatures to the approved argv, pinned image,
source, outputs and resource limits. The last argv element is a native claim
context token; for Python `-c` or shell `-c`, supply it as a positional argument.
Each quorum needs distinct approved identities, keys and declared failure domains,
including a trusted witness, with the same pipeline and artifact digest. Source,
recipient, policy, task or output substitution fails closed. Validators perform
bounded signature/JSON checks; they never execute remote code, OCI or compilers.

This is an explicitly governed trust model. Keys/domains are governance claims,
not hardware independence or trustless proof of arbitrary compilation. A corrupt
approved quorum can lie; operators must consider that risk before approving a
bounty. Ordinary successful CI is ineligible without a prior approved bounty,
matching quorum and native transaction. This does not confer PoW mining rights.

`submit_math_proof` is fully checked during native transaction validation and
state application. A valid proof becomes native pending state. After its existing
10-block challenge window, settlement atomically writes the exact proof hash to
`completed_compute_tasks` and credits `100 * reward_weight` to
`contribution_scores`. Overflow, challenge, wrong recipient and double redemption
fail. Rejected spurious challenges do not permanently withhold an eligible bounty.
Contribution scores are not tokens, stake, fork weight or block proposal rights.

`spec/openci_consensus.py` in Ziokt is the canonical generator input; Corium keeps
an identical standalone `openci_consensus.py` and a generated self-contained
monolith copy with its canonical source digest. Do not mutate an activated v1
verifier in place: deploy a distinct governed verifier/version and preserve
historical verification behavior for replay.

Tests distinguish cryptographic fixture receipts from real OCI execution.
Six local units/admission tests use real native schemas/keys/signatures and
native proposal/vote mining. CI additionally earns proposal eligibility using
real Engine Zero work, mines all 133 blocks through governance and settlement,
and independently Phoenix-rebuilds signed history. That CI must actually pass
before describing the complete native chain flow as verified.
