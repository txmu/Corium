import Init

/-! Native bootstrap and history admission model. Public genesis trust, signature
verification, SQLite durability and P2P transport are external premises. -/
namespace Corium.Bootstrap

-- BEGIN GENERATED VERIFIED GUARDS
abbrev hold_may_start (active : Bool) (requires_authorization : Bool) (authorized : Bool) : Prop :=
  (¬ (active = true) ∧ (¬ (requires_authorization = true) ∨ (authorized = true)))

abbrev block_linked (height : Nat) (digest : String) (next_height : Nat) (next_previous : String) : Prop :=
  ((next_height = (height + 1)) ∧ (next_previous = digest))

-- END GENERATED VERIFIED GUARDS

structure State where
  historyVerified : Bool
  genesisTrusted : Bool
  consensus : Bool
  writes : Bool
  deriving DecidableEq

def fresh : State := ⟨false, false, false, false⟩

def activate (s : State) : Option State :=
  if s.historyVerified && s.genesisTrusted then
    some {s with consensus := true, writes := true}
  else none

theorem fresh_node_consensus_disabled : fresh.consensus = false := rfl
theorem fresh_node_writes_disabled : fresh.writes = false := rfl
theorem fresh_node_cannot_activate : activate fresh = none := rfl

theorem unverified_history_cannot_activate (s : State) (h : s.historyVerified = false) :
    activate s = none := by
  simp [activate, h]

theorem untrusted_genesis_cannot_activate (s : State) (h : s.genesisTrusted = false) :
    activate s = none := by
  simp [activate, h]

theorem activation_preserves_history_evidence (s next : State)
    (accepted : activate s = some next) : next.historyVerified = s.historyVerified := by
  unfold activate at accepted
  split at accepted
  · cases accepted
    rfl
  · cases accepted

structure Link where
  height : Nat
  previous : Nat
  digest : Nat
  deriving DecidableEq

def linked (height digest : Nat) (block : Link) : Prop :=
  block.height = height + 1 ∧ block.previous = digest

theorem skipped_height_rejected (height digest : Nat) (b : Link)
    (skipped : height + 1 < b.height) : ¬ linked height digest b := by
  intro h
  have consecutive := h.1
  omega

theorem foreign_parent_rejected (height digest : Nat) (b : Link)
    (wrong : b.previous ≠ digest) : ¬ linked height digest b := by
  intro h
  exact wrong h.2

def publicJoinAccepted (genesis expectedGenesis identity seedIdentity : Nat) : Prop :=
  genesis = expectedGenesis ∧ identity ≠ seedIdentity

theorem copied_seed_identity_rejected (genesis expectedGenesis identity : Nat) :
    ¬ publicJoinAccepted genesis expectedGenesis identity identity := by
  intro h
  exact h.2 rfl

theorem foreign_genesis_rejected (genesis expectedGenesis identity seedIdentity : Nat)
    (wrong : genesis ≠ expectedGenesis) :
    ¬ publicJoinAccepted genesis expectedGenesis identity seedIdentity := by
  intro h
  exact wrong h.1

theorem actual_active_hold_rejects (required authorized : Bool) :
    ¬ hold_may_start true required authorized := by
  simp [hold_may_start]

theorem actual_required_authorization_cannot_be_bypassed (active : Bool) :
    ¬ hold_may_start active true false := by
  simp [hold_may_start]

theorem actual_link_rejects_height_gap (height nextHeight : Nat) (digest previous : String)
    (gap : height + 1 < nextHeight) : ¬ block_linked height digest nextHeight previous := by
  intro accepted
  have consecutive := accepted.1
  omega

theorem actual_link_rejects_foreign_parent (height nextHeight : Nat) (digest previous : String)
    (wrong : previous ≠ digest) : ¬ block_linked height digest nextHeight previous := by
  intro accepted
  exact wrong accepted.2

end Corium.Bootstrap
