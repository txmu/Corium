import Init

namespace Corium.Refinements

-- The actual semantic-state implementation sorts JSON row strings, not a
-- multiplicity function. Here encoder output is an explicit input boundary.
def canonicalRows (rows : List String) : List String :=
  rows.mergeSort (fun a b => decide (a ≤ b))

theorem canonicalRows_sorted (rows : List String) :
    (canonicalRows rows).Pairwise (fun a b => a ≤ b) := by
  have ht : ∀ a b c : String, decide (a ≤ b) = true → decide (b ≤ c) = true → decide (a ≤ c) = true := by
    intro a b c hab hbc
    simp only [decide_eq_true_eq] at *
    exact String.le_trans hab hbc
  have total : ∀ a b : String, (decide (a ≤ b) || decide (b ≤ a)) = true := by
    intro a b
    simp only [Bool.or_eq_true, decide_eq_true_eq]
    exact String.le_total a b
  simpa [canonicalRows] using List.sorted_mergeSort ht total rows

theorem canonicalRows_permutation (xs ys : List String) (h : xs.Perm ys) :
    canonicalRows xs = canonicalRows ys := by
  apply List.Perm.eq_of_sorted (le := fun a b => a ≤ b)
  · intro a b _ _ hab hba; exact String.le_antisymm hab hba
  · exact canonicalRows_sorted xs
  · exact canonicalRows_sorted ys
  · exact (List.mergeSort_perm xs _).trans (h.trans (List.mergeSort_perm ys _).symm)

def localField (key : String) : Bool :=
  key == "is_read" || key == "priority" || key == "local_path"

def projectRow (table : String) (row : List (String × String)) : List (String × String) :=
  if table == "messages" || table == "mails" then row.filter (fun kv => !localField kv.1) else row

theorem message_local_fields_dropped (row : List (String × String)) (value : String) :
    projectRow "messages" (("is_read", value) :: row) = projectRow "messages" row := by
  simp [projectRow, localField]

theorem ordinary_table_fields_retained (table : String) (row : List (String × String))
    (hm : table ≠ "messages") (hl : table ≠ "mails") : projectRow table row = row := by
  simp [projectRow, hm, hl]

-- Python notarization loop: reject duplicates, never silently count them twice.
def tally (valid : Nat → Bool) (stake : Nat → Int) : List Nat → List Nat → Int → Option Int
  | [], _, accumulated => some accumulated
  | identity :: rest, seen, accumulated =>
    if valid identity && decide (identity ∉ seen) then
      tally valid stake rest (identity :: seen) (accumulated + stake identity)
    else none

def weightSum (stake : Nat → Int) : List Nat → Int
  | [] => 0
  | identity :: rest => stake identity + weightSum stake rest

theorem tally_exact_weight (valid : Nat → Bool) (stake : Nat → Int)
    (rows seen : List Nat) (initial result : Int)
    (h : tally valid stake rows seen initial = some result) :
    result = initial + weightSum stake rows := by
  induction rows generalizing seen initial with
  | nil => simp [tally] at h; subst result; simp [weightSum]
  | cons identity rest ih =>
    simp only [tally] at h
    split at h
    · have hh := ih (identity :: seen) (initial + stake identity) h
      simp [weightSum]; omega
    · simp at h

theorem tally_no_duplicates (valid : Nat → Bool) (stake : Nat → Int)
    (rows seen : List Nat) (initial result : Int)
    (h : tally valid stake rows seen initial = some result) :
    rows.Nodup ∧ ∀ identity ∈ rows, identity ∉ seen := by
  induction rows generalizing seen initial with
  | nil => simp
  | cons identity rest ih =>
    simp only [tally] at h
    split at h
    · rename_i guard
      have hn : identity ∉ seen := by simpa using (Bool.and_eq_true_iff.mp guard).2
      obtain ⟨nd, disjoint⟩ := ih (identity :: seen) (initial + stake identity) h
      have not_rest : identity ∉ rest := by
        intro hm
        exact disjoint identity hm (by simp)
      refine ⟨by simp [nd, not_rest], ?_⟩
      intro v hv
      rcases List.mem_cons.mp hv with eq | hv
      · subst v; exact hn
      · intro hm; exact disjoint v hv (List.mem_cons.mpr (Or.inr hm))
    · simp at h

def acceptedQuorum (weight total : Int) : Bool :=
  decide (total > 0) && decide (3 * weight > 2 * total)

theorem acceptedQuorum_iff (weight total : Int) :
    acceptedQuorum weight total = true ↔ total > 0 ∧ 3 * weight > 2 * total := by
  simp [acceptedQuorum]

-- The repaired checkpoint verifier's control flow after check_header succeeds.
-- Hash validity binds contents through an external SHA-256 contract, not an axiom.
structure Header where
  hash : String
  previous : String
  height : Int
  timestamp : Int
  valid : Bool
  deriving Repr

inductive Ancestor (final : Header) : Header → Prop
  | direct (child : Header) (parent : child.previous = final.hash)
      (height : child.height = final.height + 1)
      (time : final.timestamp ≤ child.timestamp) : Ancestor final child
  | via (child middle : Header) (parent : middle.hash = child.previous)
      (height : middle.height = child.height - 1)
      (time : middle.timestamp ≤ child.timestamp)
      (tail : Ancestor final middle) : Ancestor final child

def descend (final child : Header) (headers : List Header) : Bool :=
    if child.previous = final.hash then
      decide (child.height = final.height + 1) && decide (final.timestamp ≤ child.timestamp)
    else match headers with
    | [] => false
    | middle :: rest =>
      if middle.valid && decide (middle.hash = child.previous) &&
          decide (middle.height = child.height - 1) && decide (middle.timestamp ≤ child.timestamp) then
        descend final middle rest
      else false
termination_by headers.length

def seek (anchor : String) (final : Header) : List Header → Bool
  | [] => false
  | header :: rest =>
    if header.valid then
      if header.hash = anchor then descend final header rest else seek anchor final rest
    else false

def checkpoint (anchor : String) (final : Header) (headers : List Header) : Bool :=
  final.valid && (if final.hash = anchor then true else seek anchor final headers)

theorem descend_sound (final child : Header) (headers : List Header)
    (h : descend final child headers = true) : Ancestor final child := by
  induction headers generalizing child with
  | nil =>
    simp only [descend] at h
    split at h
    · rename_i parent
      have guards := Bool.and_eq_true_iff.mp h
      exact .direct child parent (by simpa using guards.1) (by simpa using guards.2)
    · simp at h
  | cons middle rest ih =>
    simp only [descend] at h
    split at h
    · rename_i parent
      have guards := Bool.and_eq_true_iff.mp h
      exact .direct child parent (by simpa using guards.1) (by simpa using guards.2)
    · split at h
      · rename_i guard
        simp only [Bool.and_eq_true, decide_eq_true_eq] at guard
        exact .via child middle guard.1.1.2 guard.1.2 guard.2 (ih middle h)
      · simp at h

theorem seek_sound (anchor : String) (final : Header) (headers : List Header)
    (h : seek anchor final headers = true) :
    ∃ child ∈ headers, child.hash = anchor ∧ Ancestor final child := by
  induction headers with
  | nil => simp [seek] at h
  | cons child rest ih =>
    simp only [seek] at h
    split at h
    · split at h
      · rename_i found
        exact ⟨child, by simp, found, descend_sound final child rest h⟩
      · obtain ⟨parent, hm, hh, ha⟩ := ih h
        exact ⟨parent, List.mem_cons.mpr (Or.inr hm), hh, ha⟩
    · simp at h

theorem checkpoint_sound (anchor : String) (final : Header) (headers : List Header)
    (h : checkpoint anchor final headers = true) :
    final.hash = anchor ∨ ∃ child ∈ headers, child.hash = anchor ∧ Ancestor final child := by
  have hh := (Bool.and_eq_true_iff.mp h).2
  unfold checkpoint at h
  by_cases eq : final.hash = anchor
  · exact Or.inl eq
  · exact Or.inr (seek_sound anchor final headers (by simpa [checkpoint, eq] using hh))

-- Failures in replay must abort; the prior pure fold model omitted this branch.
def replayChecked (step : Nat → Nat → Option Nat) : Nat → List Nat → Option Nat
  | state, [] => some state
  | state, tx :: rest => (step state tx).bind (fun next => replayChecked step next rest)

theorem replayChecked_append (step : Nat → Nat → Option Nat)
    (history suffix : List Nat) (state : Nat) :
    replayChecked step state (history ++ suffix) =
      (replayChecked step state history).bind (fun next => replayChecked step next suffix) := by
  induction history generalizing state with
  | nil => rfl
  | cons tx rest ih =>
    simp only [List.cons_append, replayChecked]
    cases hs : step state tx with
    | none => rfl
    | some next => simpa using ih next

end Corium.Refinements
