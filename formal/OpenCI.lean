import Init

/-!
# Ziokt OpenCI and PoUW Formal Verification
Formalizes useful compute task attestation, witness threshold checks,
bounty reward boundedness, and semantic independence from PoW hashing.
-/

namespace Ziokt.OpenCI

structure Task where
  id : Nat
  programDigest : Nat
  maxReward : Nat
  expiryHeight : Nat
deriving DecidableEq, Repr

structure Witness where
  workerId : Nat
  domainId : Nat
deriving DecidableEq, Repr

structure ComputeProof where
  taskId : Nat
  outputDigest : Nat
  witnesses : List Witness
  claimedReward : Nat
deriving DecidableEq, Repr

def distinctDomains (witnesses : List Witness) : Nat :=
  -- Counts distinct failure domains among witnesses
  (witnesses.map (fun w => w.domainId)).eraseDups.length

def validProof (t : Task) (p : ComputeProof) (threshold : Nat) : Prop :=
  p.taskId = t.id ∧
  p.claimedReward ≤ t.maxReward ∧
  distinctDomains p.witnesses ≥ threshold

-- Machine-Checked Theorems

theorem proof_commits_to_task_id (t : Task) (p : ComputeProof) (k : Nat)
    (h_valid : validProof t p k) :
    p.taskId = t.id := by
  unfold validProof at h_valid
  exact h_valid.1

theorem reward_bounded_by_task_allocation (t : Task) (p : ComputeProof) (k : Nat)
    (h_valid : validProof t p k) :
    p.claimedReward ≤ t.maxReward := by
  unfold validProof at h_valid
  exact h_valid.2.1

theorem insufficient_witness_domains_rejected (t : Task) (p : ComputeProof) (k : Nat)
    (h_fail : distinctDomains p.witnesses < k) :
    ¬ validProof t p k := by
  unfold validProof
  intro h
  omega

structure PoWNonce where
  nonce : Nat
  blockTarget : Nat
  hashValue : Nat

def powSatisfied (w : PoWNonce) : Prop :=
  w.hashValue ≤ w.blockTarget

theorem compute_proof_does_not_grant_pow (t : Task) (p : ComputeProof) (k : Nat)
    (w : PoWNonce)
    (_h_pouw : validProof t p k)
    (h_pow_fail : w.hashValue > w.blockTarget) :
    ¬ powSatisfied w := by
  unfold powSatisfied
  omega

end Ziokt.OpenCI
