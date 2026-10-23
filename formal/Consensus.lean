import Init

/-!
# Ziokt Sovereign Network: Formal Consensus Verification
Machine-checked theorems proving core consensus safety invariants:
1. Dynamic difficulty retarget bounds clamp timespan and keep target within [MIN, MAX].
2. Discrete integer block work floor(2^256 / (target + 1)) is strictly positive.
3. Cumulative chain work is strictly monotonic.
4. Fork choice deterministically prefers heavier cumulative work and tie-breaks irreflexively.
5. PoW block validity is independent of miner stake or validator registry.
-/

namespace Ziokt.Consensus

-- 1. Parameters and Targets
def MIN_DIFFICULTY_BITS : Nat := 4
def MAX_DIFFICULTY_BITS : Nat := 240
def TARGET_SPACING : Nat := 60
def RETARGET_INTERVAL : Nat := 10
def DAMPING_FACTOR : Nat := 4

def MAX_TARGET : Nat := (2 ^ (256 - MIN_DIFFICULTY_BITS)) - 1
def MIN_TARGET : Nat := 2 ^ (256 - MAX_DIFFICULTY_BITS)

def validTarget (t : Nat) : Prop :=
  MIN_TARGET ≤ t ∧ t ≤ MAX_TARGET

def clampTimespan (actual expected : Nat) : Nat :=
  let minT := expected / DAMPING_FACTOR
  let maxT := expected * DAMPING_FACTOR
  if actual < minT then minT
  else if actual > maxT then maxT
  else actual

def retarget (prevTarget actual expected : Nat) : Nat :=
  let clamped := clampTimespan actual expected
  let exp := if expected = 0 then 1 else expected
  let raw := (prevTarget * clamped) / exp
  if raw < MIN_TARGET then MIN_TARGET
  else if raw > MAX_TARGET then MAX_TARGET
  else raw

def blockWork (target : Nat) : Nat :=
  (2 ^ 256) / (target + 1)

def cumulativeWork (parentTotal target : Nat) : Nat :=
  parentTotal + blockWork target

structure ChainTip where
  hash : Nat
  cumulativeWork : Nat
deriving DecidableEq

def forkPreferred (candidate current : ChainTip) : Bool :=
  if candidate.cumulativeWork > current.cumulativeWork then true
  else if candidate.cumulativeWork < current.cumulativeWork then false
  else decide (candidate.hash < current.hash)

structure Miner where
  pubkey : Nat
  stake : Nat

structure BlockCandidate where
  height : Nat
  miner : Miner
  target : Nat
  nonceDigest : Nat

def powValid (b : BlockCandidate) : Prop :=
  validTarget b.target ∧ b.nonceDigest ≤ b.target

-- 2. Machine-Checked Theorems

theorem clampTimespan_lower_bound (actual expected : Nat) :
    clampTimespan actual expected ≥ expected / DAMPING_FACTOR := by
  dsimp [clampTimespan, DAMPING_FACTOR]
  split
  · exact Nat.le_refl _
  · split
    · have : expected * 4 ≥ expected / 4 := by omega
      exact this
    · omega

theorem clampTimespan_upper_bound (actual expected : Nat) :
    clampTimespan actual expected ≤ expected * DAMPING_FACTOR := by
  dsimp [clampTimespan, DAMPING_FACTOR]
  split
  · have : expected / 4 ≤ expected * 4 := by omega
    exact this
  · split
    · exact Nat.le_refl _
    · omega

theorem retarget_in_bounds (prevTarget actual expected : Nat) :
    validTarget (retarget prevTarget actual expected) := by
  dsimp [validTarget, retarget]
  split
  · split
    · have : MIN_TARGET ≤ MAX_TARGET := by decide
      exact ⟨Nat.le_refl _, this⟩
    · split
      · have : MIN_TARGET ≤ MAX_TARGET := by decide
        exact ⟨this, Nat.le_refl _⟩
      · omega
  · split
    · have : MIN_TARGET ≤ MAX_TARGET := by decide
      exact ⟨Nat.le_refl _, this⟩
    · split
      · have : MIN_TARGET ≤ MAX_TARGET := by decide
        exact ⟨this, Nat.le_refl _⟩
      · omega

theorem blockWork_positive (target : Nat) (h : target ≤ MAX_TARGET) :
    blockWork target > 0 := by
  unfold blockWork MAX_TARGET MIN_DIFFICULTY_BITS at *
  have ht_lt : target + 1 ≤ 2 ^ 256 := by
    have : (2 ^ 252 - 1) + 1 ≤ 2 ^ 256 := by decide
    omega
  have ht_pos : target + 1 > 0 := by omega
  exact Nat.div_pos ht_lt ht_pos

theorem cumulative_work_monotonic (parentTotal target : Nat) (h : target ≤ MAX_TARGET) :
    cumulativeWork parentTotal target > parentTotal := by
  unfold cumulativeWork
  have hw := blockWork_positive target h
  omega

theorem forkChoice_prefers_heavier (c1 c2 : ChainTip)
    (h : c1.cumulativeWork > c2.cumulativeWork) :
    forkPreferred c1 c2 = true := by
  unfold forkPreferred
  simp [h]

theorem forkChoice_rejects_lighter (c1 c2 : ChainTip)
    (h : c1.cumulativeWork < c2.cumulativeWork) :
    forkPreferred c1 c2 = false := by
  have hnot : ¬ (c1.cumulativeWork > c2.cumulativeWork) := by omega
  unfold forkPreferred
  simp [hnot, h]

theorem forkChoice_irreflexive (c : ChainTip) :
    forkPreferred c c = false := by
  unfold forkPreferred
  have hnot : ¬ (c.cumulativeWork > c.cumulativeWork) := by omega
  have hnot2 : ¬ (c.cumulativeWork < c.cumulativeWork) := by omega
  have hnot3 : ¬ (c.hash < c.hash) := Nat.lt_irrefl c.hash
  simp [hnot, hnot2, hnot3]

theorem unstaked_miner_pow_independence
    (m1 m2 : Miner) (h target nonceDigest : Nat)
    (h_valid : powValid ⟨h, m1, target, nonceDigest⟩) :
    powValid ⟨h, m2, target, nonceDigest⟩ := by
  exact h_valid

/- A protocol interface model. The trusted context must be reconstructed from
accepted history by the caller. Signature/transaction booleans stand for results
of concrete verifiers; this does not prove those cryptographic implementations. -/
structure GovernedContext where
  parentHeight : Nat
  parentHash : Nat
  parentWork : Nat
  activationHeight : Nat
  policyApproved : Bool
  expectedTarget : Nat

structure SignedCandidate where
  height : Nat
  previousHash : Nat
  minerPublicKey : Nat
  claimedTarget : Option Nat
  nonceDigest : Nat
  signatureVerified : Bool
  transactionsVerified : Bool

def protocolValid (s : GovernedContext) (b : SignedCandidate) : Prop :=
  s.policyApproved = true ∧ b.height ≥ s.activationHeight ∧
  b.height = s.parentHeight + 1 ∧ b.previousHash = s.parentHash ∧
  validTarget s.expectedTarget ∧ b.signatureVerified = true ∧
  b.transactionsVerified = true ∧ b.nonceDigest ≤ s.expectedTarget ∧
  (b.claimedTarget = none ∨ b.claimedTarget = some s.expectedTarget)

instance (s : GovernedContext) (b : SignedCandidate) : Decidable (protocolValid s b) :=
  by unfold protocolValid validTarget; infer_instance

def validateAndCredit (s : GovernedContext) (b : SignedCandidate) : Option Nat :=
  if protocolValid s b then some (s.parentWork + blockWork s.expectedTarget) else none

theorem credited_work_uses_governed_target (s : GovernedContext) (b : SignedCandidate)
    (total : Nat) (h : validateAndCredit s b = some total) :
    protocolValid s b ∧ total = s.parentWork + blockWork s.expectedTarget := by
  unfold validateAndCredit at h
  split at h
  · rename_i valid
    exact ⟨valid, (Option.some.inj h).symm⟩
  · contradiction

theorem false_target_cannot_receive_credit (s : GovernedContext) (b : SignedCandidate)
    (claimed : Nat) (hclaim : b.claimedTarget = some claimed)
    (hdiff : claimed ≠ s.expectedTarget) : validateAndCredit s b = none := by
  have invalid : ¬ protocolValid s b := by
    intro valid
    rcases valid.2.2.2.2.2.2.2.2 with absent | equal
    · rw [hclaim] at absent
      contradiction
    · rw [hclaim] at equal
      exact hdiff (Option.some.inj equal)
  simp [validateAndCredit, invalid]

-- These model entrypoints intentionally delegate to one kernel. Production
-- equivalence requires demonstrating this delegation and equal reconstructed inputs.
def acceptBlock (s : GovernedContext) (b : SignedCandidate) := validateAndCredit s b
def syncBlock (s : GovernedContext) (b : SignedCandidate) := validateAndCredit s b
def replayBlock (s : GovernedContext) (b : SignedCandidate) := validateAndCredit s b
def reorgBlock (historical : GovernedContext) (b : SignedCandidate) := validateAndCredit historical b

theorem validation_entrypoints_agree (s : GovernedContext) (b : SignedCandidate) :
    acceptBlock s b = syncBlock s b ∧ syncBlock s b = replayBlock s b ∧
    replayBlock s b = reorgBlock s b := by
  exact ⟨rfl, rfl, rfl⟩

def registeredAdmission (s : GovernedContext) (b : SignedCandidate)
    (_validatorRegistry : List Nat) := validateAndCredit s b

theorem signed_block_registry_independence (s : GovernedContext) (b : SignedCandidate)
    (oldRegistry newRegistry : List Nat) :
    registeredAdmission s b oldRegistry = registeredAdmission s b newRegistry := by
  rfl

def targetAtHeight (oldTarget newTarget activation height : Nat) : Nat :=
  if height < activation then oldTarget else newTarget

theorem governance_target_not_retroactive (oldTarget newTarget activation height : Nat)
    (before : height < activation) :
    targetAtHeight oldTarget newTarget activation height = oldTarget := by
  simp [targetAtHeight, before]

end Ziokt.Consensus
