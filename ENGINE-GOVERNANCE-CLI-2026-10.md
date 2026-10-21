# Compute engine governance CLI repair, 2026-10-21

Scope: `_internal_governance_propose_engine` and
`_internal_governance_vote_engine`, their native transaction dispatch and error
reporting. The trust boundary remains CLI input → native identity signing →
locally pending transaction → independent native consensus/governance.

## Confirmed findings

- `vote-engine` used `$vote_tx_type` without a local definition. The ordinary
  command supplied an empty type; unrelated inherited/global values could select
  another transaction type. ShellCheck identified SC2154 on the extracted actual
  functions. Controlled dispatcher tests reproduce global-variable influence.
- Both helpers treated nonempty submitter output as success even if submission
  returned failure. This could label a failed/partial native operation successful.

The vote helper now dispatches the fixed native `vote_on_compute_engine` type.
Both helpers require successful native submission and a canonical last-line
transaction hash, return failure otherwise, and explicitly describe successful
local admission as **pending native consensus**, not active-engine approval.
The native transaction schema, signature algorithm, stake/contribution rules,
scheduled activation, disclosure authorization and experimental network guards
are unchanged. No network operation or production governance action was run.

## Validation and limits

Three local controlled dispatcher/failure units passed. Extracted actual helper
ShellCheck has no warning after excluding SC1111 for existing Chinese typographic
quotes inside literal output text; shell syntax passed. These are narrow checks,
not a full-project clean-SAST claim.

CI adds a real native fixture test creating and verifying actual signed pending
proposal/vote transactions with the original native key/signature routine. It
asserts that no compute engine becomes active from local submission. Existing
consensus/native suites remain enabled. The fixture is not a mainnet operation,
reward settlement or end-to-end engine activation proof.

## Upgrade and rollback

Deploy only the reviewed native source revision after CI. Existing databases,
keys, transaction formats and chain history require no migration. Back up native
configuration/state and retain the prior source revision for rollback. Native
provider entrypoint fingerprints must be reapproved explicitly by the operator
when upgrading; do not disable fingerprint checks. Production services were not
restarted or reconfigured by this source repair.

The actual current registration interface is native
`governance propose-engine` / `governance vote-engine`, followed by original
consensus and scheduled enactment. There is no `pouw_engine` command in this
source revision. A Ziokt/OpenCI adapter must use the real interface and cannot
replace the owner's proposal/vote or mark `is_active` directly.
