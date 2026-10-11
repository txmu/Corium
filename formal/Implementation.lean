import Init

/- Source-oriented algorithms. External processes, parsing and storage are not
   modeled by Lean; see COVERAGE.md for the exact refinement boundary. -/
namespace Corium.Implementation

structure Hop where
  right : Bool
  sibling : String
  deriving DecidableEq, Repr

def advance (hash : String → String → String) (current : String) (hop : Hop) : String :=
  if hop.right then hash current hop.sibling else hash hop.sibling current

def nextLevel (hash : String → String → String) : List String → List String
  | [] => []
  | [a] => [hash a a]
  | a :: b :: rest => hash a b :: nextLevel hash rest

structure PairStep where
  current : String
  parent : String
  hop : Hop
  index : Nat
  deriving Repr

-- Same pairing/index movement as Python siblings(); singleton is duplicated.
def stepAt (hash : String → String → String) : Nat → List String → Option PairStep
  | _, [] => none
  | 0, [a] => some ⟨a, hash a a, ⟨true, a⟩, 0⟩
  | _ + 1, [_] => none
  | 0, a :: b :: _ => some ⟨a, hash a b, ⟨true, b⟩, 0⟩
  | 1, a :: b :: _ => some ⟨b, hash a b, ⟨false, a⟩, 0⟩
  | i + 2, _ :: _ :: rest =>
      (stepAt hash i rest).map (fun s => { s with index := s.index + 1 })

theorem step_properties (hash : String → String → String)
    (xs : List String) (i : Nat) (s : PairStep) (h : stepAt hash i xs = some s) :
    xs[i]? = some s.current ∧
    (nextLevel hash xs)[s.index]? = some s.parent ∧
    advance hash s.current s.hop = s.parent := by
  cases xs with
  | nil => simp [stepAt] at h
  | cons a rest =>
    cases rest with
    | nil =>
      cases i with
      | zero => simp [stepAt] at h; subst s; simp [nextLevel, advance]
      | succ i => simp [stepAt] at h
    | cons b rest =>
      cases i with
      | zero => simp [stepAt] at h; subst s; simp [nextLevel, advance]
      | succ i =>
        cases i with
        | zero => simp [stepAt] at h; subst s; simp [nextLevel, advance]
        | succ i =>
          cases hs : stepAt hash i rest with
          | none => simp [stepAt, hs] at h
          | some inner =>
            simp [stepAt, hs] at h
            subst s
            obtain ⟨hc, hp, hh⟩ := step_properties hash rest i inner hs
            exact ⟨by simpa using hc, by simpa [nextLevel] using hp, hh⟩
termination_by xs.length

theorem step_exists (hash : String → String → String)
    (xs : List String) (i : Nat) (target : String) (h : xs[i]? = some target) :
    ∃ s, stepAt hash i xs = some s := by
  cases xs with
  | nil => simp at h
  | cons a rest =>
    cases rest with
    | nil =>
      cases i with
      | zero => exact ⟨_, rfl⟩
      | succ i => simp at h
    | cons b rest =>
      cases i with
      | zero => exact ⟨_, rfl⟩
      | succ i =>
        cases i with
        | zero => exact ⟨_, rfl⟩
        | succ i =>
          obtain ⟨s, hs⟩ := step_exists hash rest i target (by simpa using h)
          exact ⟨{ s with index := s.index + 1 }, by simp [stepAt, hs]⟩
termination_by xs.length

theorem nextLevel_length_le (hash : String → String → String) (xs : List String) :
    (nextLevel hash xs).length ≤ xs.length := by
  cases xs with
  | nil => simp [nextLevel]
  | cons a rest =>
    cases rest with
    | nil => simp [nextLevel]
    | cons b rest =>
      have ih := nextLevel_length_le hash rest
      simp [nextLevel] at *
      omega
termination_by xs.length

theorem nextLevel_shorter (hash : String → String → String) (a b : String) (rest : List String) :
    (nextLevel hash (a :: b :: rest)).length < (a :: b :: rest).length := by
  have ih := nextLevel_length_le hash rest
  simp [nextLevel]
  omega

-- Fuel makes the executable Lean model total. length(leaves) is sufficient;
-- generation_complete below proves this, rather than assuming termination.
def generateAt (hash : String → String → String) : Nat → Nat → List String → Option (List Hop)
  | _, _, [] => none
  | _, i, [_] => if i = 0 then some [] else none
  | 0, _, _ :: _ :: _ => none
  | fuel + 1, i, a :: b :: rest =>
      match stepAt hash i (a :: b :: rest) with
      | none => none
      | some s => (generateAt hash fuel s.index (nextLevel hash (a :: b :: rest))).map (s.hop :: ·)

def rootFuel (hash : String → String → String) : Nat → List String → Option String
  | _, [] => none
  | _, [a] => some a
  | 0, _ :: _ :: _ => none
  | fuel + 1, a :: b :: rest => rootFuel hash fuel (nextLevel hash (a :: b :: rest))

def verifyPath (hash : String → String → String) : String → List Hop → String
  | current, [] => current
  | current, hop :: rest => verifyPath hash (advance hash current hop) rest

theorem generation_sound (hash : String → String → String) (fuel i : Nat)
    (xs : List String) (target : String) (path : List Hop)
    (ht : xs[i]? = some target) (hg : generateAt hash fuel i xs = some path) :
    ∃ result, rootFuel hash fuel xs = some result ∧ verifyPath hash target path = result := by
  induction fuel generalizing i xs target path with
  | zero =>
    cases xs with
    | nil => simp [generateAt] at hg
    | cons a rest =>
      cases rest with
      | nil =>
        cases i with
        | zero => simp at ht; subst target; simp [generateAt] at hg; subst path; exact ⟨a, rfl, rfl⟩
        | succ i => simp at ht
      | cons b rest => simp [generateAt] at hg
  | succ fuel ih =>
    cases xs with
    | nil => simp [generateAt] at hg
    | cons a rest =>
      cases rest with
      | nil =>
        cases i with
        | zero => simp at ht; subst target; simp [generateAt] at hg; subst path; exact ⟨a, rfl, rfl⟩
        | succ i => simp at ht
      | cons b rest =>
        cases hs : stepAt hash i (a :: b :: rest) with
        | none => simp [generateAt, hs] at hg
        | some s =>
          cases hp : generateAt hash fuel s.index (nextLevel hash (a :: b :: rest)) with
          | none => simp [generateAt, hs, hp] at hg
          | some tail =>
            simp [generateAt, hs, hp] at hg
            subst path
            obtain ⟨hc, hn, hh⟩ := step_properties hash (a :: b :: rest) i s hs
            have eq : s.current = target := Option.some.inj (hc.symm.trans ht)
            obtain ⟨result, hr, hv⟩ := ih s.index _ s.parent tail hn hp
            refine ⟨result, hr, ?_⟩
            simpa only [verifyPath, ← eq, hh] using hv

theorem generation_complete (hash : String → String → String) (fuel i : Nat)
    (xs : List String) (target : String)
    (size : xs.length ≤ fuel + 1) (ht : xs[i]? = some target) :
    ∃ path, generateAt hash fuel i xs = some path := by
  induction fuel generalizing xs i target with
  | zero =>
    cases xs with
    | nil => simp at ht
    | cons a rest =>
      cases rest with
      | nil =>
        cases i with
        | zero => exact ⟨[], rfl⟩
        | succ i => simp at ht
      | cons b rest => simp at size
  | succ fuel ih =>
    cases xs with
    | nil => simp at ht
    | cons a rest =>
      cases rest with
      | nil =>
        cases i with
        | zero => exact ⟨[], rfl⟩
        | succ i => simp at ht
      | cons b rest =>
        obtain ⟨s, hs⟩ := step_exists hash (a :: b :: rest) i target ht
        obtain ⟨_, hn, _⟩ := step_properties hash (a :: b :: rest) i s hs
        have small := nextLevel_shorter hash a b rest
        have bound : (nextLevel hash (a :: b :: rest)).length ≤ fuel + 1 := by omega
        obtain ⟨path, hp⟩ := ih s.index _ s.parent bound hn
        exact ⟨s.hop :: path, by simp [generateAt, hs, hp]⟩

-- Python's arbitrary-precision int XOR after the 64-hex-digit input guard.
def xorDistance (a b : Nat) : Nat := a ^^^ b

theorem xorDistance_symmetric (a b : Nat) : xorDistance a b = xorDistance b a :=
  Nat.xor_comm a b

theorem xorDistance_bounded (a b : Nat) (ha : a < 2^256) (hb : b < 2^256) :
    xorDistance a b < 2^256 := Nat.xor_lt_two_pow ha hb

-- Successful database snapshot operations, one path owned by one BASHPID.
-- Active depth d represents source depth d+1, so zero-depth active states
-- cannot be constructed. A foreign owner is modeled by commitOwned below.
inductive DBTx where
  | idle (current : Nat)
  | active (saved current depthMinusOne : Nat)
  deriving DecidableEq, Repr

def dbBegin : DBTx → DBTx
  | .idle current => .active current current 0
  | .active saved current d => .active saved current (d+1)
def dbWrite : DBTx → Nat → DBTx
  | .idle _, value => .idle value
  | .active saved _ d, value => .active saved value d
def dbCommit : DBTx → DBTx
  | .idle current => .idle current
  | .active _ current 0 => .idle current
  | .active saved current (d+1) => .active saved current d
def dbCommitOwned (sameOwner : Bool) (state : DBTx) : DBTx :=
  if sameOwner then dbCommit state else state
def dbRollback : DBTx → DBTx
  | .idle current => .idle current
  | .active saved _ _ => .idle saved

theorem nested_begin_keeps_outer_snapshot (saved current d : Nat) :
    dbBegin (.active saved current d) = .active saved current (d+1) := rfl

theorem inner_commit_does_not_commit_outer (saved current d : Nat) :
    dbCommit (.active saved current (d+1)) = .active saved current d := rfl

theorem nested_rollback_after_inner_commit (saved value : Nat) :
    dbRollback (dbCommit (dbWrite (dbBegin (dbBegin (.idle saved))) value)) = .idle saved := rfl

theorem rollback_all_depths (saved current d : Nat) :
    dbRollback (.active saved current d) = .idle saved := rfl

theorem foreign_commit_noop (state : DBTx) : dbCommitOwned false state = state := rfl

theorem rollback_idempotent (state : DBTx) : dbRollback (dbRollback state) = dbRollback state := by
  cases state <;> rfl

-- Precise Kahn fanout loop: signed decrement then enqueue exactly on zero.
structure KahnState where
  degree : Nat → Int
  queue : List Nat

def fanout : List Nat → KahnState → KahnState
  | [], s => s
  | v :: rest, s =>
    let degree := s.degree v - 1
    fanout rest ⟨fun x => if x = v then degree else s.degree x,
                 if degree = 0 then s.queue ++ [v] else s.queue⟩

theorem fanout_degree (successors : List Nat) (s : KahnState) (v : Nat) :
    (fanout successors s).degree v = s.degree v - (successors.count v : Int) := by
  induction successors generalizing s with
  | nil => simp [fanout]
  | cons u rest ih =>
    simp only [fanout]
    rw [ih]
    simp only [List.count_cons]
    by_cases h : v = u
    · subst u; simp; omega
    · simp [h, Ne.symm h]

def insertEdge (edge : Nat × Nat) (edges : List (Nat × Nat)) : List (Nat × Nat) :=
  if edge ∈ edges then edges else edges ++ [edge]

theorem duplicate_edge_noop (edge : Nat × Nat) (edges : List (Nat × Nat)) (h : edge ∈ edges) :
    insertEdge edge edges = edges := by simp [insertEdge, h]

theorem install_filter_preserves_order (keep : Nat → Bool) (order : List Nat) :
    (order.filter keep).Sublist order := List.filter_sublist

-- End-to-end array algorithm: every valid index terminates and verifies.
theorem array_merkle_correct (hash : String → String → String)
    (xs : List String) (i : Nat) (target : String) (ht : xs[i]? = some target) :
    ∃ path result,
      generateAt hash xs.length i xs = some path ∧
      rootFuel hash xs.length xs = some result ∧
      verifyPath hash target path = result := by
  obtain ⟨path, hg⟩ := generation_complete hash xs.length i xs target (by omega) ht
  obtain ⟨result, hr, hv⟩ := generation_sound hash xs.length i xs target path ht hg
  exact ⟨path, result, hg, hr, hv⟩

end Corium.Implementation
