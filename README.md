# Corium

[简体中文](README.zh-CN.md) · [Documentation](docs/README.md) · [Ziokt v1.0](https://github.com/txmu/Ziokt-Releases/releases/tag/v1.0)

Corium is the native chain, governance, package and recovery foundation of the Ziokt ecosystem. Its production entrypoint is the independently deliverable Bash artifact `corix_v108.sh`. Native PoW admission, dual-chain/DNA rules, application transactions, governed work policies and history reconstruction have distinct validation responsibilities.

## Native ownership

Corium owns its network configuration, identities, chain databases, package trust, native permissions and recovery decisions. Ziokt integration is optional and disabled by default. A federation signature cannot replace native transaction validity, publisher trust or an authorized governance transition.

The production artifact embeds native helpers. The repository also contains standalone verification and recovery tools; their deployment and the distinction between models and production kernels are documented in [architecture](docs/architecture.en.md).

## First checks

Run read-only checks from a source checkout before choosing a new isolated state root:

```sh
bash -n corix_v108.sh
python3 ci/static-checks.py
```

For a complete prebuilt Ziokt node, use the [VPS deployment guide](https://github.com/txmu/Ziokt-Releases/blob/main/VPS_BOOTSTRAP.zh-CN.md). Never bootstrap a new network over an existing production root or copy another node's private identity.

## Read the operator documentation

| Guide | Purpose |
| --- | --- |
| [Getting started](docs/getting-started.en.md) | State roots, explicit networks and optional Ziokt access |
| [Architecture](docs/architecture.en.md) | Production admission, dual chains, DHT and application state |
| [Operations and recovery](docs/operations.en.md) | Peer exclusions, reorganization, synchronization and checkpoints |
| [Security](docs/security.en.md) | Trust boundaries, keys, privacy and unsafe recovery shortcuts |
| [Verification](docs/verification.en.md) | Native CI, Lean models and source correspondence |
| [Document catalog](docs/REFERENCE.en.md) | Policy references, formal inventories and dated evidence |

## Validation

`validation.yml` exercises the native artifact on Ubuntu 22.04/24.04 with fixed seeds. `remaining-coverage.yml` covers routed and anonymous networks, real package managers, filesystem cases and crash/power-cut recovery. `openci-consensus.yml` checks native governance and settlement. Formal CI checks Lean and implementation correspondence. Consult the [Actions history](https://github.com/txmu/Corium/actions) and release evidence for exact commits; the existence of a workflow is not a passing result.

The ecosystem release is **v1.0**. The native entrypoint's `v108` name is its component identifier and is retained. Independent physical multi-node and mainnet-history acceptance require their own evidence.
