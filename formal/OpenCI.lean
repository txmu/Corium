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

-- -------------------------------------------------------------
-- Configurable Node Resource Governance (Node-Specific Capacity)
-- -------------------------------------------------------------

structure NodeResourceConfig where
  maxNativeExponent : Nat
  maxMemoryBytes : Nat
  externalEngineActive : Bool
deriving DecidableEq, Repr

def requiredMemoryBytes (exponent : Nat) : Nat :=
  (exponent / 8) * 32

def taskAdmittedByNode (cfg : NodeResourceConfig) (exponent : Nat) : Prop :=
  cfg.externalEngineActive = true ∨
  (exponent ≤ cfg.maxNativeExponent ∧ requiredMemoryBytes exponent ≤ cfg.maxMemoryBytes)

theorem native_task_respects_node_exponent_limit (cfg : NodeResourceConfig) (p : Nat)
    (h_native : cfg.externalEngineActive = false)
    (h_admit : taskAdmittedByNode cfg p) :
    p ≤ cfg.maxNativeExponent := by
  unfold taskAdmittedByNode at h_admit
  rcases h_admit with h_ext | h_lim
  · rw [h_native] at h_ext; contradiction
  · exact h_lim.1

theorem native_task_respects_node_memory_limit (cfg : NodeResourceConfig) (p : Nat)
    (h_native : cfg.externalEngineActive = false)
    (h_admit : taskAdmittedByNode cfg p) :
    requiredMemoryBytes p ≤ cfg.maxMemoryBytes := by
  unfold taskAdmittedByNode at h_admit
  rcases h_admit with h_ext | h_lim
  · rw [h_native] at h_ext; contradiction
  · exact h_lim.2

theorem excessive_exponent_rejected_when_native (cfg : NodeResourceConfig) (p : Nat)
    (h_native : cfg.externalEngineActive = false)
    (h_excess : p > cfg.maxNativeExponent) :
    ¬ taskAdmittedByNode cfg p := by
  unfold taskAdmittedByNode
  intro h
  rcases h with h_ext | h_lim
  · rw [h_native] at h_ext; contradiction
  · omega

theorem external_engine_admits_arbitrary_exponent (cfg : NodeResourceConfig) (p : Nat)
    (h_ext : cfg.externalEngineActive = true) :
    taskAdmittedByNode cfg p := by
  unfold taskAdmittedByNode
  left
  exact h_ext

-- -------------------------------------------------------------
-- Gerbicz Mathematical Recurrence Checkpoint Model
-- -------------------------------------------------------------

structure GerbiczStep where
  iteration : Nat
  stateResidue : Nat
deriving DecidableEq, Repr

def gerbiczStepValid (s1 s2 : GerbiczStep) (squarings : Nat → Nat → Nat) : Prop :=
  s1.iteration < s2.iteration ∧
  s2.stateResidue = squarings s1.stateResidue (s2.iteration - s1.iteration)

theorem corrupted_gerbicz_residue_rejected (s1 s2 : GerbiczStep) (squarings : Nat → Nat → Nat)
    (h_corrupt : s2.stateResidue ≠ squarings s1.stateResidue (s2.iteration - s1.iteration)) :
    ¬ gerbiczStepValid s1 s2 squarings := by
  unfold gerbiczStepValid
  intro h
  exact h_corrupt h.2

theorem gerbicz_sequence_strictly_advances (s1 s2 : GerbiczStep) (squarings : Nat → Nat → Nat)
    (h_valid : gerbiczStepValid s1 s2 squarings) :
    s1.iteration < s2.iteration := by
  unfold gerbiczStepValid at h_valid
  exact h_valid.1

-- -------------------------------------------------------------
-- PrimeNet Protocol Status Separation Model
-- -------------------------------------------------------------

inductive PrimeNetBusinessResult where
  | success (receiptCode : Nat) (detail : Nat)
  | error (errorCode : Nat) (detail : Nat)
deriving DecidableEq, Repr

structure HttpResponse where
  httpStatusCode : Nat
  businessPayload : Option PrimeNetBusinessResult
deriving DecidableEq, Repr

def primeNetConfirmed (resp : HttpResponse) : Prop :=
  resp.httpStatusCode = 200 ∧
  match resp.businessPayload with
  | some (PrimeNetBusinessResult.success 0 _) => true
  | _ => false

theorem http_200_alone_insufficient_for_confirmation (payload : Option PrimeNetBusinessResult)
    (h_not_success : match payload with
                     | some (PrimeNetBusinessResult.success 0 _) => false
                     | _ => true) :
    ¬ primeNetConfirmed ⟨200, payload⟩ := by
  unfold primeNetConfirmed
  intro h
  have hb := h.2
  revert h_not_success
  cases payload with
  | none => simp at hb
  | some b =>
    cases b with
    | success code detail =>
      cases code with
      | zero => simp
      | succ c => simp at hb
    | error err detail => simp at hb

theorem official_success_zero_confirmed (detail : Nat) :
    primeNetConfirmed ⟨200, some (PrimeNetBusinessResult.success 0 detail)⟩ := by
  unfold primeNetConfirmed
  exact ⟨rfl, rfl⟩

-- -------------------------------------------------------------
-- Task Lease Persistence Model (24-Hour Heartbeat Recovery)
-- -------------------------------------------------------------

structure TaskLease where
  token : Nat
  deadline : Nat
  checkpoint : Nat
deriving DecidableEq, Repr

def leaseActive (l : TaskLease) (now : Nat) : Prop :=
  now < l.deadline

def restoreLeases (now : Nat) (leases : List TaskLease) : List TaskLease :=
  leases.filter (fun l => decide (now < l.deadline))

theorem restored_leases_are_active (now : Nat) (leases : List TaskLease) (l : TaskLease)
    (h_restored : l ∈ restoreLeases now leases) :
    leaseActive l now := by
  unfold restoreLeases leaseActive at *
  have hm := List.mem_filter.mp h_restored
  simp only [decide_eq_true_eq] at hm
  exact hm.2

theorem expired_lease_not_restored (now : Nat) (leases : List TaskLease) (l : TaskLease)
    (h_expired : l.deadline ≤ now) :
    l ∉ restoreLeases now leases := by
  unfold restoreLeases
  intro h_mem
  have hm := List.mem_filter.mp h_mem
  simp only [decide_eq_true_eq] at hm
  have : now < l.deadline := hm.2
  omega

end Ziokt.OpenCI
