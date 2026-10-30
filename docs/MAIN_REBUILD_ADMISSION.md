# Explicit rebuilt-mainnet admission

`rebuild_authorization.py` verifies optional genesis-validator-signed admission for
an operator-authorized native rebuild of `ziokt-main`. It binds the original
genesis, canonical database path, native source SHA-256, verified branch anchor,
maximum height and expiration. Descendant links must be continuous. This does not
replace native block, transaction, governance or work verification. Keep original
branches archived and production identities unchanged.

Replay now updates `chain_info` after each verified block. Fast-forward executes
already-scheduled governance changes before choosing the activation-height
verifier, matching the existing native producer. Policy, voting windows, work
targets and asset rules remain under their existing native checks.

Validation: `python3 -m unittest test_rebuild_authorization test_replay_tip_cache
test_work_consensus -q`, and `python3 -m unittest
test_work_activation_reorg.ActivationReorgTests.test_activation_boundary_fast_forward
-q`; `python3 formal/check_source.py`; `bash -n corix_v108.sh`.
The activation regression uses real native TLS and signed work. Its isolated
policy registry fixture is not mainnet governance evidence. Live acceptance must
separately establish identical canonical hashes and blocks from both miners.

Rollback: stop consensus; restore a reviewed previous source with its matching
signed permission. Removing permission closes mainnet admission. Do not reactivate
an archived invalid-signature branch for availability. Preserve audit archives;
no private key transfer or replacement is needed.

Canonical mining and reorganization share the system writer lock so rollback
snapshots cannot restore over a concurrent native commit. Mining releases that
lock after commit and before peer broadcasts. Canonical parent reads query the
block table rather than trusting the derived `chain_info` cache. Targeted native
regressions cover a poisoned cache and a real held-writer-lock reorganization.

The optional `CORIUM_MINER_POLL_SECONDS` (5–300, default 5) only controls
node-local PoW candidate scheduling. Legacy polling remains five seconds.
Remove the environment override to roll back scheduling without touching ledger
or consensus policy. A slower poll reduces low-difficulty empty-block races; it
is not a block-validity rule or a guarantee against normal PoW forks.

Mining and reorganization snapshots cover ledger/application state, not the
independent global DHT routing/cache database. Otherwise a rejected branch could
resurrect obsolete peer identities learned before a valid routing repair.
Transaction creation shares the canonical writer lock, so a rollback cannot
silently erase concurrent admission. Cached orphan objects may remain; they are
not confirmations and native signatures/work still decide admission. An actual
interrupted native TLS reorg test checks that a newer routing row survives.
