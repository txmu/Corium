# Ziokt Sovereign Network: Mainnet Independence & Node Operator Guide

**Network ID**: `ziokt-main`  
**Current Milestone**: Sovereign Network — Open Consensus, Independent Bootstrap & Lean Verification  
**Status**: Production Ready & Fully Verified  

---

## 1. Introduction & Sovereign Architecture

The **Ziokt Sovereign Network** represents the transition of the Ziokt ecosystem from a single-operator deployment into an open, decentralized, permissionless distributed system. 

Under the sovereign architecture:
- **Block Production (PoW)**: Open to anyone who computes valid proof of work with an SECP256K1 key pair. **No stake, no token balance, and no operator license is required.**
- **Network Governance (PoS)**: Corium's original staking and governance mechanics are preserved for protocol parameter updates, validator proposals, and engine upgrades under strict **$\ge 110$ block timelocks**, but no longer schedule block production.
- **Useful Work (PoUW)**: OpenCI handles verifiable compute tasks, worker attestations, and credit payouts. Compute attestation credits are strictly decoupled from PoW hashing and voting power.
- **Trustless Bootstrap**: Independent full nodes can synchronize, independently verify, and follow the canonical chain from Genesis to the tip without relying on or trusting the founding node.
- **Content Availability**: The Content Fabric, Library, and Netnews operate via decentralized content-addressed (CID) peer chunks that persist across peer nodes even if the founder content server goes permanently dark.

---

## 2. Mainnet History & Immutable Anchors

The live mainnet (`ziokt-main`) possesses persistent state that must **never be reset, wiped, or rewritten**. All sovereign implementations respect and preserve the complete chain history:

```
[Genesis Block 0] -------------------> [Block 64] -------------------> [Block 782 (Current)]
  599b7512c4...                         9caf67936f...                    43f921998c...
  * Network Born                        * Work v2 Activated              * Empty Blocks Halted
  * Legacy PoS Blocks (0..63)           * SHA-256 PoW Mining             * Cumulative Work: 782,000
                                        * Engine: consensus/work-weight:2 * Consensus: pow-v2
```

### Immutable Mainnet Checkpoints:
- **Genesis Block Hash**: `599b7512c4ffb640520433f0772f00e78198ad958f444d25459dbca8c38ce0fa`
- **Work v2 Activation Height**: `64`
- **Work v2 Policy Commitment**: `9caf67936f6d1881296b97f5a5524f344ab06547d4eec78fc352f695228fa8df`
- **Current Tip Height**: `782`
- **Current Tip Hash**: `43f921998c9f523f49b271882935c24c50c5c68cd5830e1a3d4d8f5d961fd9fe`
- **Cumulative Work**: `782000` units

To independently verify the entire 783-block mainnet history from genesis:
```bash
python3 /home/admin/Corium/verify_mainnet_history.py
```

---

## 3. Node Roles & Permissions Matrix

To eliminate confusion between different network participant types, Ziokt defines 6 distinct roles:

| Node Role | Identity Basis | Stake Requirement | Function & Scope |
| :--- | :--- | :---: | :--- |
| **PoW Miner** | SECP256K1 Key Pair | **None (0 ZKT)** | Packages transactions, calculates PoW nonce, signs block header, collects fees. |
| **Full Verification Node** | Any Local Host | **None** | Downloads blocks, verifies consensus rules, maintains local state ledger. |
| **PoS Governance Validator** | Registered in `validators` | $\ge 1$ ZKT Staked | Votes on protocol proposals, engine transitions, slashing appeals. |
| **OpenCI Worker** | Compute Worker Key | **None** | Executes containerized compute tasks, submits cryptographic attestations. |
| **P2P Mesh Relayer** | Shadow6 / DHT Peer | **None** | Propagates valid blocks, transactions, and content chunks across the network. |
| **Content Fabric Node** | Content Server ID | **None** | Stores and seeds immutable chunks for Library books and Netnews articles. |

---

## 4. Permissionless Mining Guide

### 4.1 Generating Miner Identity
Any participant can generate a miner key pair with zero external permissions:

```bash
# Generate private key
openssl ecparam -name secp256k1 -genkey -noout -out /path/to/miner_identity.key

# Extract public key in canonical SubjectPublicKeyInfo PEM format
openssl ec -in /path/to/miner_identity.key -pubout -out /path/to/miner_identity.key.pub

# Compute miner identity hash (SHA-256 of the PEM public key)
sha256sum /path/to/miner_identity.key.pub | awk '{print $1}'
```

### 4.2 Mining Controls & Empty Block Policy
To avoid wasting resources on low-power infrastructure, empty block generation is prevented by default:
- **Automatic Trigger**: When transactions enter the mempool (`transactions WHERE block_height IS NULL`), the consensus daemon immediately initiates candidate block packaging and PoW hashing.
- **Idle State**: When the mempool is empty, the node stays in low-overhead peer listening mode.
- **Manual Empty Block Mining**: If testing or intentionally mining empty blocks, set:
  ```bash
  export CORIUM_ALLOW_EMPTY_BLOCKS=1
  # OR
  touch /home/admin/.local/share/ziokt-production/corium/allow_empty_blocks
  ```
- **Pausing Mining**: To pause local mining without stopping the node:
  ```bash
  touch /home/admin/.local/share/ziokt-production/corium/pause_mining
  ```

---

## 5. Dynamic Difficulty & Cumulative Work

### 5.1 Difficulty Retargeting Algorithm
In accordance with Bitcoin-style difficulty principles, dynamic retargeting adjusts difficulty to maintain a stable average block interval:
- **Target Spacing**: 60 seconds (`TARGET_SPACING = 60`)
- **Retarget Window**: Every 10 blocks (`RETARGET_INTERVAL = 10`)
- **Damping Limits**: Actual timespan is clamped to $[T_{\text{expected}} / 4, 4 \cdot T_{\text{expected}}]$ ($[150\text{s}, 2400\text{s}]$) to prevent wild oscillations from temporary hash spikes or drops.
- **Integer Math**: Pure integer operations ensure identical results across any architecture or language.

### 5.2 Cumulative Chain Work Formula
Instead of naive block height or fixed weight increments, chains are selected strictly by cumulative work:
$$\text{block\_work} = \left\lfloor \frac{2^{256}}{\text{target} + 1} \right\rfloor$$
$$\text{cumulative\_work}_{N} = \text{cumulative\_work}_{N-1} + \text{block\_work}_N$$

- **Fork Choice Rule**:
  1. The branch with **strictly greater cumulative work** is selected as the canonical chain.
  2. If cumulative work is identical, the deterministic tie-breaker is the **lexicographically lower block hash**.

---

## 6. Governed Upgrade Path: Activating Work v3

The transition from static Work v2 (4 bits) to Dynamic Difficulty Work v3 is governed by Corium's on-chain governance protocol:

1. **Proposal**: A validator submits a `propose_new_compute_engine` transaction with `pkg_id="consensus/work-weight:3"`.
2. **Timelock Delay**: An enforced delay of $\ge 110$ blocks ensures all node operators have adequate advance notice before enactment.
3. **Activation Height**: At the specified enactment height (e.g., Height 1000), `ConsensusValidationCore` automatically transitions to dynamic retargeting without any chain restart or state loss.
4. **Historical Continuity**: Blocks 0–63 remain validated as PoS; Blocks 64–999 remain validated as Work v2; Blocks 1000+ execute dynamic retargeting.

---

## 7. Content Fabric Decentralization

The Ziokt Content Fabric distributes immutable media, books, and articles:
- **Content Addressing**: All items are addressed by SHA-256 chunk hashes and root Content Identifiers (CIDs).
- **Founder Immunity**: Chunks replicated across any peer nodes (Nodes 1, 2, ...) remain fully accessible and verifiable.
- **Decentralized Publishing**: Any node can publish signed articles or Library books locally, and other nodes fetch and seed them via the P2P DHT mesh.

---

## 8. Node Operations & Monitoring

### Checking Real-time Node Status
```bash
python3 /home/admin/Corium/sovereign_status.py
```
Outputs a full status dashboard including:
- Current Height & Tip Hash
- Cumulative Chain Work & Target Difficulty
- Active Roles (PoW miner, OpenCI worker, Relayer, etc.)
- Mining switches & mempool status
- Lean 4 formal verification status

### Running Full Protocol Verification
```bash
# 1. Consensus Kernel Tests
python3 /home/admin/Corium/test_consensus_core.py

# 2. Multi-Node Sovereign Disconnection Simulation
python3 /home/admin/Corium/test_multinode_sovereign.py

# 3. Content Fabric Sovereign Survival Test
python3 /home/admin/Ziokt/tests/test_content_sovereign_survival.py

# 4. Lean 4 Formal Verification & Axioms Audit
bash /home/admin/Corium/formal/check_all_formal.sh
```

### Managing the Production Consensus Service
```bash
# Check service status
systemctl status ziokt-corium-consensus.service

# View consensus logs
journalctl -u ziokt-corium-consensus.service -n 50 -f
```
