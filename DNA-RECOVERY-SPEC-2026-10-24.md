# Ziokt native recovery and DNA/RNA sidechain — implementation specification

## Operator decisions

The operator authorized a new primary branch beginning at height **51**, sharing
only the existing, replayable prefix 0–50. The initial primary target is height
**64**, reached by generating and validating actual new blocks. The existing
785 block records remain the historical sidechain. Main and side are distinct
chains with different post-transition protocols; one must not be an updated copy
or mirror of the other's state.

DNA means A/C/G/T base encoding and antiparallel complementary strands. RNA means
A/C/G/U transmission, with explicit chain/policy/sender identities, sequence and
expiry. It does not mean a newly invented cryptographic hardness assumption.

The operator additionally requested free cooperative governance, especially
protection against acquisition/merger. Implemented registry rules reject merger,
sale/delegation of control, membership transfer, capital-weighted voting and
charter replacement. Independently governed cooperatives may federate without
combining identities/member lists; either cooperative may withdraw without the
other's approval. An individual member may leave using their own signature.

## Implemented and locally checked components

- `dna_protocol.py`: bounded canonical ACGT encoding, reverse-complement duplexes,
  intact-strand recovery against a caller-authenticated payload root, and native
  secp256k1-signed RNA frames bound to chain, policy, sender, sequence and 120-second
  validity windows. The caller must persist the accepted RNA sequence atomically.
- `cooperative_protocol.py`: deterministic registry commands signed by actual
  native keys and bound to the prior registry root, chain and sequence. Strict
  member supermajorities count identities once; all founders and new members
  must consent. Unknown actions/extra fields and forbidden takeover actions fail.
- `formal/DNA.lean`: byte roundtrip, complementary strand involution/injectivity,
  RNA chain and sequence rejection, with crypto verification as an external premise.
- `formal/Cooperatives.lean`: explicit forbidden operations, strict quorum,
  duplicate ballot rejection, member/identity preservation under federation,
  sequence advance and member exit. These models are not a proof that all native
  Bash/SQLite/P2P paths implement the registry semantics.

Nine Python regression tests exercise the actual implementations. These
components are **not yet enabled in production consensus**. Presence of a module,
passing tests, or a Lean theorem inventory is not activation evidence.

## Required native integration and transition rules

1. Preserve the existing branch and all immutable objects. Build the new primary
   in separate databases by replaying prefix 0–50; do not copy current derived
   state and declare it valid. Record supplied genesis and authority dependencies.
2. Bind new chain identity to a public, signed recovery declaration containing
   the exact prefix checkpoint, complete genesis configuration commitment,
   replayed state commitment, protocol/verifier source commitments, and activation
   rules. This is a new recovery trust boundary, not a backdated governance vote.
3. Existing governance requires 110 blocks of delay. A proposal at height 51
   cannot enact under those rules at height 64. Initial recovery rules therefore
   belong to the explicit recovery declaration; later governance follows the
   declared, non-retroactive voting/enactment rules.
4. Use different signature and proof domains for primary and DNA sidechain.
   Bind *transactions*, blocks, governance, RNA and all derived state to their
   applicable chain/version. Legacy wallet or asset paths that sign unscoped
   transactions must be upgraded, not accepted through a compatibility bypass.
5. Encode the DNA commitment in the signed sidechain block, and verify both
   strands against the expected block/rule context. Candidate-supplied roots,
   target, weight, source hashes or current-state snapshots cannot be authority.
6. RNA messages authenticate the decoded payload root and metadata. Persist replay
   state only after signature and payload verification; use atomic monotonic
   updates under concurrent delivery. Bounded storage/CPU/size limits apply before
   expensive work. Wire delivery must be exercised over actual local processes.
7. Apply cooperative state transitions in the same transactional validation
   kernel for mining, admission, sync, reorganization and replay. Route treasury
   and asset ownership changes through that kernel before claiming asset-level
   acquisition protection. Registry metadata alone does not lock external assets.
8. Validate real primary blocks 51–64, replay them from the declared prefix,
   exercise both protocols independently, then change service routing and public
   roles atomically. Verify Gateway/MCP/web/source/CI identities together. Keep
   rollback and branch archives; do not clear the hold before those checks.

## Security and social scope

A reversible encoding adds no entropy or cryptographic security. An antiparallel
strand permits recovery when at least one strand is intact and its expected root
is already authenticated. It cannot reconstruct arbitrary destruction of both
strands. Signatures, authenticated commitments, consensus rules and availability
provide the relevant protections; molecular terminology alone does not.

The registry defines a member as a public-key identity. It does not establish one
human per key, independent witnesses/operators, non-collusion, or absence of key
sales. Capital can influence real people outside the ledger. The rules reject
specified on-chain takeover actions under the pinned protocol; they do not prove
that economic domination, an off-chain acquisition or a socially adopted hard
fork is impossible. No transaction or governance path may identify a person as
"large capital" merely from a balance or an unverified label.

The old sidechain retains its known provenance gaps: NNS state at 51 and missing
canonical governance activation before 64. DNA activation cannot retroactively
validate those records. Any continuing sidechain snapshot must be labelled as an
explicit legacy checkpoint/trust input, with new DNA protection beginning only
at its announced activation height. The main recovery must not inherit that
unverified state.
