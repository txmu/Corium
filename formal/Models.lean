import Init

/- Small algorithm models, not a verification of the Bash implementation. -/
namespace Corium

-- 1. Exhaustive topological search: intentionally simpler than production Kahn.
def topoOK (edges : List (Nat × Nat)) (order : List Nat) : Bool :=
  decide order.Nodup && edges.all (fun (u, v) =>
    order.contains u && order.contains v && decide (order.idxOf u < order.idxOf v))

def search (ok : List Nat → Bool) : List (List Nat) → Option (List Nat)
  | [] => none
  | x :: xs => if ok x then some x else search ok xs

theorem search_sound (ok : List Nat → Bool) (xs : List (List Nat))
    (h : search ok xs = some result) : ok result = true := by
  induction xs with
  | nil => simp [search] at h
  | cons x xs ih =>
    simp only [search] at h
    split at h
    · cases h; assumption
    · exact ih h

theorem search_complete (ok : List Nat → Bool) (xs : List (List Nat))
    (h : ∃ x ∈ xs, ok x = true) : ∃ r, search ok xs = some r := by
  induction xs with
  | nil => simp at h
  | cons x xs ih =>
    by_cases hx : ok x = true
    · exact ⟨x, by simp [search, hx]⟩
    · obtain ⟨y, hy, hok⟩ := h
      simp only [List.mem_cons] at hy
      rcases hy with heq | hy
      · subst y; contradiction
      · simpa [search, hx] using ih ⟨y, hy, hok⟩

theorem topo_search_valid (edges : List (Nat × Nat)) (candidates : List (List Nat))
    (h : search (topoOK edges) candidates = some result) :
    result.Nodup ∧ edges.all (fun (u, v) =>
      result.contains u && result.contains v && decide (result.idxOf u < result.idxOf v)) = true := by
  have hs := search_sound (topoOK edges) candidates h
  simpa [topoOK] using hs

-- 2. Weighted quorum. The overlap bound models union weight ≤ total weight.
def quorum (weight total : Nat) : Prop := 3 * weight > 2 * total

theorem quorum_overlap (a b overlap total : Nat)
    (ha : quorum a total) (hb : quorum b total)
    (unionBound : a + b ≤ total + overlap) : 3 * overlap > total := by
  unfold quorum at *
  omega

theorem exact_two_thirds_rejected (k : Nat) : ¬ quorum (2 * k) (3 * k) := by
  unfold quorum
  omega

-- 3. Semantic normalization: project away local fields and represent rows
-- as a multiplicity function. This is a model, not the Python JSON encoding.
def semantic (rows : List (Nat × Nat)) (key : Nat) : Nat :=
  ((rows.map Prod.fst).filter (fun x => x == key)).length

theorem local_field_irrelevant (rows : List (Nat × Nat)) (value local₁ local₂ key : Nat) :
    semantic ((value, local₁) :: rows) key =
      semantic ((value, local₂) :: rows) key := by rfl

theorem row_swap_irrelevant (rows : List (Nat × Nat)) (a b : Nat × Nat) (key : Nat) :
    semantic (a :: b :: rows) key = semantic (b :: a :: rows) key := by
  simp [semantic, List.filter_cons]
  split <;> split <;> simp_all <;> omega

theorem row_permutation_irrelevant (xs ys : List (Nat × Nat))
    (h : xs.Perm ys) (key : Nat) : semantic xs key = semantic ys key := by
  exact ((h.map Prod.fst).filter (fun x => x == key)).length_eq

-- 4. XOR distance, bitwise model; a node ID is a fixed vector of these bits.
def xorBit (a b : Bool) : Bool := Bool.xor a b

theorem xor_symmetric (a b : Bool) : xorBit a b = xorBit b a := by
  cases a <;> cases b <;> rfl

theorem xor_zero_iff (a b : Bool) : xorBit a b = false ↔ a = b := by
  cases a <;> cases b <;> simp [xorBit, Bool.xor]

theorem xor_vector_zero_iff (a b : Fin 256 → Bool) :
    (∀ i, xorBit (a i) (b i) = false) ↔ a = b := by
  constructor
  · intro h; funext i; exact (xor_zero_iff (a i) (b i)).mp (h i)
  · intro h; subst b; intro i; exact (xor_zero_iff (a i) (a i)).mpr rfl

-- 5. Merkle reconstruction. Hash is arbitrary; no collision claim is made.
inductive Tree where
  | leaf : Nat → Tree
  | node : Tree → Tree → Tree

def root (hash : Nat → Nat → Nat) : Tree → Nat
  | .leaf x => x
  | .node l r => hash (root hash l) (root hash r)

-- true means the sibling is on the right; path runs leaf to root.
def wrap : Tree → List (Bool × Tree) → Tree
  | t, [] => t
  | t, (right, sibling) :: rest =>
      wrap (if right then .node t sibling else .node sibling t) rest

def verifyPath (hash : Nat → Nat → Nat) : Nat → List (Bool × Tree) → Nat
  | x, [] => x
  | x, (right, sibling) :: rest =>
      verifyPath hash (if right then hash x (root hash sibling)
        else hash (root hash sibling) x) rest

theorem merkle_reconstruction (hash : Nat → Nat → Nat)
    (path : List (Bool × Tree)) (t : Tree) :
    verifyPath hash (root hash t) path = root hash (wrap t path) := by
  induction path generalizing t with
  | nil => rfl
  | cons item rest ih =>
    rcases item with ⟨right, sibling⟩
    cases right
    · simpa [verifyPath, wrap, root] using ih (.node sibling t)
    · simpa [verifyPath, wrap, root] using ih (.node t sibling)

-- 6. Deterministic replay and reorganization from a common history.
def replay (step : Nat → Nat → Nat) (state : Nat) (txs : List Nat) : Nat :=
  txs.foldl step state

theorem replay_append (step : Nat → Nat → Nat) (s : Nat) (history suffix : List Nat) :
    replay step s (history ++ suffix) = replay step (replay step s history) suffix := by
  simp [replay, List.foldl_append]

def reorg (step : Nat → Nat → Nat) (genesis : Nat)
    (history targetSuffix : List Nat) : Nat :=
  replay step (replay step genesis history) targetSuffix

theorem reorg_equals_target_replay (step : Nat → Nat → Nat)
    (genesis : Nat) (history targetSuffix : List Nat) :
    reorg step genesis history targetSuffix = replay step genesis (history ++ targetSuffix) := by
  exact (replay_append step genesis history targetSuffix).symm

-- 7. Snapshot transaction: ideal atomic operations, one outer transaction.
inductive Tx where
  | idle : Nat → Tx
  | active : (saved current : Nat) → Tx

def beginTx (s : Nat) : Tx := .active s s
def writeTx (t : Tx) (value : Nat) : Tx :=
  match t with
  | .idle s => .idle s
  | .active saved _ => .active saved value
def commitTx : Tx → Tx
  | .idle s => .idle s
  | .active _ current => .idle current
def recoverTx : Tx → Tx
  | .idle s => .idle s
  | .active saved _ => .idle saved

theorem rollback_restores (before after : Nat) :
    recoverTx (writeTx (beginTx before) after) = .idle before := by rfl
theorem committed_survives (before after : Nat) :
    recoverTx (commitTx (writeTx (beginTx before) after)) = .idle after := by rfl
theorem recovery_idempotent (t : Tx) : recoverTx (recoverTx t) = recoverTx t := by
  cases t <;> rfl

end Corium
