import Init

/-! Reversible base encoding, reverse-complement duplexes, and RNA domain checks.
No collision resistance, signature unforgeability, human uniqueness, or complete
production implementation refinement is asserted by this model. -/
namespace Corium.DNA

inductive Base where
  | a | c | g | t
  deriving DecidableEq, Repr

def pair : Base → Base
  | .a => .t
  | .c => .g
  | .g => .c
  | .t => .a

def antisense (strand : List Base) : List Base := strand.reverse.map pair

theorem pair_involutive (b : Base) : pair (pair b) = b := by
  cases b <;> rfl

theorem antisense_involutive (s : List Base) : antisense (antisense s) = s := by
  simp [antisense, List.map_reverse, List.map_map, Function.comp_def, pair_involutive]

theorem distinct_strand_changes_duplex (a b : List Base) (h : a ≠ b) :
    antisense a ≠ antisense b := by
  intro eq
  have same := congrArg antisense eq
  exact h (by simpa only [antisense_involutive] using same)

structure ByteBases where
  first : Nat
  second : Nat
  third : Nat
  fourth : Nat
  deriving DecidableEq

def encodeByte (n : Nat) : ByteBases :=
  ⟨n / 64 % 4, n / 16 % 4, n / 4 % 4, n % 4⟩

def decodeByte (b : ByteBases) : Nat :=
  64 * b.first + 16 * b.second + 4 * b.third + b.fourth

theorem byte_roundtrip (n : Nat) (h : n < 256) : decodeByte (encodeByte n) = n := by
  simp only [decodeByte, encodeByte]
  omega

structure RNAHeader where
  chain : Nat
  policy : Nat
  sender : Nat
  sequence : Nat
  issuedAt : Nat
  expiresAt : Nat

-- Cryptographic root/signature verification is an explicit external premise.
def rnaAccepted (h : RNAHeader) (chain policy sender previous now : Nat)
    (cryptographicallyVerified : Bool) : Prop :=
  h.chain = chain ∧ h.policy = policy ∧ h.sender = sender ∧
  previous < h.sequence ∧ h.issuedAt ≤ now ∧ now ≤ h.expiresAt ∧
  h.expiresAt = h.issuedAt + 120 ∧ cryptographicallyVerified = true

theorem other_chain_rejected (h : RNAHeader) (chain policy sender previous now : Nat)
    (verified : Bool) (wrong : h.chain ≠ chain) :
    ¬ rnaAccepted h chain policy sender previous now verified := by
  intro accepted
  exact wrong accepted.1

theorem repeated_sequence_rejected (h : RNAHeader) (chain policy sender previous now : Nat)
    (verified : Bool) (old : h.sequence ≤ previous) :
    ¬ rnaAccepted h chain policy sender previous now verified := by
  intro accepted
  have newer := accepted.2.2.2.1
  omega

end Corium.DNA
