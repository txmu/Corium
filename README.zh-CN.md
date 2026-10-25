# Corium

[English](README.md) · [中文文档](docs/README.zh-CN.md) · [Ziokt v1.0](https://github.com/txmu/Ziokt-Releases/releases/tag/v1.0)

Corium 是 Ziokt 生态的原生链、治理、软件包与恢复基础。生产入口为可独立交付的 Bash 文件 `corix_v108.sh`。原生 PoW 接纳、双链/DNA 规则、应用交易、受治理的贡献策略和历史重建，各自承担明确的验证职责。

## 原生权限归属

网络配置、节点身份、链数据库、软件包信任、原生权限和恢复决策由 Corium 自己管理。Ziokt 接入是默认关闭的可选能力；联邦签名不能替代原生交易有效性、发布者信任或治理批准。

生产文件内嵌原生助手。仓库还提供独立验证与恢复工具；交付要求和模型与生产内核的区别见 [架构说明](docs/architecture.zh-CN.md)。

## 首次检查

从源码目录执行只读检查，再为新节点选择隔离的状态根目录：

```sh
bash -n corix_v108.sh
python3 ci/static-checks.py
```

完整预构建 Ziokt 节点使用 [VPS 部署教程](https://github.com/txmu/Ziokt-Releases/blob/main/VPS_BOOTSTRAP.zh-CN.md)。不要覆盖已有生产状态初始化新网络，也不要复制另一节点的私有身份。

## 操作手册

| 文档 | 解决的问题 |
| --- | --- |
| [入门](docs/getting-started.zh-CN.md) | 状态根、显式网络、可选 Ziokt 接入 |
| [架构](docs/architecture.zh-CN.md) | 生产接纳、双链、DHT 与应用状态 |
| [运维与恢复](docs/operations.zh-CN.md) | 对端排除、重组、同步与检查点 |
| [安全](docs/security.zh-CN.md) | 信任边界、密钥、隐私和恢复禁区 |
| [验证](docs/verification.zh-CN.md) | 原生 CI、Lean 模型与源码对应 |
| [全部文档](docs/REFERENCE.zh-CN.md) | 策略参考、形式化清单及历史证据 |

## 验证方式

`validation.yml` 在 Ubuntu 22.04/24.04、固定种子下验证生产文件；`remaining-coverage.yml` 覆盖路由和匿名网络、真实包管理器、文件系统、崩溃与断电恢复；`openci-consensus.yml` 检查原生治理与结算；形式化 CI 检查 Lean 及实现对应。精确提交结果以 [Actions](https://github.com/txmu/Corium/actions) 和发布证据为准，存在工作流不等于已经通过。

生态发行版保持 **v1.0**。入口中的 `v108` 是组件标识，继续保留。独立物理多节点与主网历史的可信性需要各自的验收证据。
