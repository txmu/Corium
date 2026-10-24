# Historical provenance incident and recovery scope — 2026-10-24

## Confirmed findings

The production work activation proposal
`442e314873cb7649ea6b5e8df82a09cb62943c7ef44ed97d6aa0268b9a2835e6`
is flagged confirmed at height 1 but is absent from that block's transaction list.
The OpenCI proposal
`f474e162a8d25ffb47e379cbe2b107f86830f527ea430a03e14d2d3c1ea6100a`
has the same inclusion problem. Database `block_height` and `is_active` values
cannot establish that a signed block committed either proposal. Native Work and
OpenCI activation now require actual canonical transaction membership. This is
an additional guard; complete voting authorization still requires history replay.
Changing verifier source bytes changes its source commitment: the patch does not
relabel an old verifier hash as the new code or silently authorize old policies.

All legacy headers and signatures through height 63 verify with the supplied
public genesis validator configuration. This does NOT establish application
validity or bind the entire genesis allocation: the legacy genesis header hashes
the timestamp/header, not the complete validator and allocation configuration.
The genesis configuration remains an explicit trust input.

The full native replay correctly rejects pre-activation auxiliary PoW records.
A diagnostic COPY retained the exact signed legacy headers/transactions, excluded
those nonbinding auxiliary rows, and replayed the legacy transitions. It reached
height 50, then rejected the height 51 NNS update
`8755a7b527b92125613b1c1fb019d5c454936f7d00dd7ff294dfd89fd44ffddf`.
That update names domains absent from both the genesis reservations and the
previously replayed registration transactions. Current ownership validation
cannot derive the required state from the committed prefix. Authentic historical
rules/activation evidence may explain old acceptance; this report does not invent
those rules or retroactively declare a new exception.

`audit_history_provenance.py` is a read-only evidence audit and returns nonzero for
missing canonical commitments. Its scoped signature check does not claim full
transaction execution, governance replay or on-chain state-root verification.
`verify_mainnet_history.py --require-full` continues to fail closed.

## Network fixes and bounded evidence

`dht_find_closest_nodes` previously returned the last loop comparison, reporting
failure whenever it found fewer than k peers. It now succeeds for a nonempty
result and excludes the local node from remote candidates. Empty routing tables
still fail honestly. The production routing table currently has no remote peers;
this patch cannot manufacture public network propagation.

ANNOUNCE_BLOCK previously looked up the sender key again after the envelope had
already authenticated it, rejecting new unstaked identities. It now reuses that
verified key for the inner announcement signature. The three-process local test
uses the actual production TLS handler, pinned test certificates and signed
messages. PING, STORE, known-block announcement and survivor exchange after the
founder process stops pass. This does not prove acceptance of a new native PoW
branch, public discovery or multiple operators. The prior four-process consensus
model experiment remains separately scoped.

Sync now propagates routing lookup failure instead of treating an empty routing
table as evidence that the chain is up to date. A self-only routing table fails
cleanly. Sync regressions use distinct peer transport identities while retaining
the same genesis validator for consensus signatures; they no longer model a
remote node as the local node's own transport identity.

## Production protection and recovery decision

Automatic consensus mining is stopped under a persisted safety hold. Existing
blocks, transactions, immutable objects and derived state have not been rewritten.
Consistent database backups preserve the current branch. Native deployment checks
the hold BEFORE changing sources and does not restart held consensus. A managed
systemd ExecCondition also blocks startup/reboot while the hold is active or malformed. Gateway and
MCP expose only allowlisted public hold fields, never private backup paths.
Mining, reorganization, sync staging, snapshot import and live derived-state rebuild also share the same local safety check. Read-only replay remains available. Content/query services remain available; their availability is not history proof.

Recovery requires either authentic historical protocol/activation/registration
records or an explicit decision to establish a new valid branch/network. A new
branch must retain the original archive, revalidate application transactions,
commit real proposals and votes at new heights, and pass full replay before
cutover. It must not backdate governance, inject an accepted current state, or
silently delete inconvenient historical rows. A software-only repair cannot
produce missing signed historical commitments.

The earlier remote full Lean run and `formal-release-gate` both succeeded:
https://github.com/txmu/Corium/actions/runs/40037295961 . New source revisions must
have their own local/remote gate evidence. Exact declarations and premises remain
in `formal/THEOREMS.md`; no full production refinement or third-party crypto audit
is claimed.
