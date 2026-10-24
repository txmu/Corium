import Init

/-! Cooperative governance rules for key identities. Real human uniqueness,
non-collusion, cryptographic verification and off-chain key sales are outside
this model. Federation links do not transfer membership or identity. -/
namespace Corium.Cooperatives

inductive Action where
  | create | admitMember | leave | federate | unfederate
  | merge | sellControl | delegateControl | transferMembership | capitalWeighted | changeCharter
  deriving DecidableEq

def allowed : Action → Bool
  | .create | .admitMember | .leave | .federate | .unfederate => true
  | _ => false

theorem merger_rejected : allowed .merge = false := rfl

theorem sale_of_control_rejected : allowed .sellControl = false := rfl

theorem charter_takeover_rejected : allowed .changeCharter = false := rfl

def quorum (voters members : Nat) : Prop := members > 0 ∧ 3 * voters > 2 * members

instance (voters members : Nat) : Decidable (quorum voters members) :=
  inferInstanceAs (Decidable (members > 0 ∧ 3 * voters > 2 * members))

theorem minority_cannot_pass (voters members : Nat) (h : 3*voters ≤ 2*members) :
    ¬ quorum voters members := by
  unfold quorum
  omega

def uniqueBallot (votes : List Nat) : Prop := votes.Nodup

theorem duplicate_vote_rejected (v : Nat) (votes : List Nat) :
    ¬ uniqueBallot (v :: v :: votes) := by
  simp [uniqueBallot]

structure Cooperative where
  id : Nat
  members : List Nat
  partners : List Nat
  sequence : Nat
  deriving DecidableEq

def joinFederation (c : Cooperative) (partner : Nat) : Cooperative :=
  {c with partners := partner :: c.partners, sequence := c.sequence + 1}

theorem federation_preserves_members (c : Cooperative) (partner : Nat) :
    (joinFederation c partner).members = c.members := rfl

theorem federation_preserves_identity (c : Cooperative) (partner : Nat) :
    (joinFederation c partner).id = c.id := rfl

theorem federation_advances_sequence (c : Cooperative) (partner : Nat) :
    (joinFederation c partner).sequence > c.sequence := by
  simp [joinFederation]

def memberExit (c : Cooperative) (member : Nat) : Cooperative :=
  {c with members := c.members.filter (fun m => m != member), sequence := c.sequence + 1}

theorem exited_member_removed (c : Cooperative) (member : Nat) :
    member ∉ (memberExit c member).members := by
  simp [memberExit]

end Corium.Cooperatives
