# 源码对应与证明边界

这份清单区分算法证明、人工源码对应和真实执行测试。没有 Bash/Python/SQL
语义翻译器，因此当前不能宣称整份 `corix_v108.sh` 已被形式化验证。
`source-map.json` 固定人工审查过的函数版本；哈希一致只能证明未发生漂移。

| 模块 | 源码对应 | 本轮 Lean 成果 | 尚未证明 |
|---|---|---|---|
| Merkle | `_internal_ibc_codec` 中 `next_level` / `siblings` / `verify_merkle` | 同序配对、奇数节点复制、索引移动、足够长度界、路径生成完备性与正确性；任意有效索引的生成路径验证得到同一根 | Python 解释器、JSON 验证、`nodes.index` 的首个匹配语义、SHA-256 实现与密码学安全 |
| IBC 检查点 | 同一 codec 的 `verify` 分支 | 向下回溯的链路、高度和时间约束；接受意味着最终块就是检查点，或它是所提供检查点的历史祖先 | 完整消息绑定分支、JSON/base64、字节编码、源码执行与模型的机械对应；信任锚来源的治理安全 |
| DB 事务 | `db_begin_transaction` / `db_commit_transaction` / `_internal_db_restore_snapshot` | 外层快照保持、内层提交仅减深度、任意深度回滚、外来 owner 提交不变、回滚幂等 | 文件不存在、备份丢失、I/O 失败、SQL/WAL、跨多个 DB 原子性、进程复用、故障持久化 |
| Kahn | `dep_resolve_topological` 的 fanout、边去重、最终过滤 | 真实“先减度，再在零时入队”的循环；剩余入度等于原入度减去后继出现次数；重复边不重复注册；过滤保持相对顺序 | 全循环不变量与总正确性、图发现、安装状态/外部依赖、slot 解析、Shell 数组与整数溢出；旧 `Models.lean` 的穷举排序不对应生产 Kahn |
| Exodus | `_internal_verify_exodus_quorum` 的循环和阈值 | 有符号整型累计、成功返回的精确计权、公证者无重复、严格 2/3 且总权重大于零的分支 | 快照结构、数据库查询、身份集合构造、时间窗、签名验证器、全流程对应 |
| 语义状态 | `_internal_semantic_state` 的 row 排序/字段删除 | JSON 行编码字符串的实际排序模型与排列不变性；messages 的 is_read 删除；其他表保留字段 | 全部表排除规则、SQL NULL/BLOB/浮点、JSON 编码、schema、外层对象序列化及模型与 Python 字符串排序对应 |
| XOR | `kademlia_distance` 的 `int(hex) ^ int(hex)` | 自然数 XOR 对称、256 bit 范围保持；旧模型还证明零值的逐 bit 判定 | 正则与十六进制解析、Python 执行与 Lean 的机械对应 |
| replay/reorg | `_internal_replay_chain_state` / `_blockchain_reorganize_to` | 带失败返回的重放分段律；旧模型的纯重放/重组关系 | 所有交易类型的状态转移、前置历史验证、治理时序、临时目录、实际回滚、全流程对应 |
| PoW 难度与权重 | `consensus_core.py` (calculate_retarget, calculate_block_work) | `Consensus.lean`: 动态难度调幅上下界、离散区块工作量严格正定、累计链工作严格单调递增、分叉选择确定性与反自反性、无抵押矿工 PoW 独立性 | 真实互联网网络时延分布、SHA-256 碰撞阻力（作为密码学公理假设） |
| 状态机与迁移边界 | `_internal_replay_chain_state`、`applyBlock` | `StateMachine.lean`: 状态机确定性执行、无效 PoW 区块在 v2 激活后严格拒绝、转账余额守恒律、64高度迁移分界确定性、链重放单步归纳 | 底层数据库 I/O 故障、OS 崩溃与硬件掉电 |
| PoS 治理与 PoW 分权 | `_protocol_execute_scheduled_changes`、`_protocol_vote` | `Governance.lean`: 治理提案时间锁约束（≥110高度延迟）、2/3 超级多数法定交集定理、PoS 权益无法绕过 PoW 目标检查 | 链下治理投票社交共识 |
| OpenCI 计算证明 | `openci_consensus.py` | `OpenCI.lean`: 任务标识严格绑定、奖励受限不超分配上限、多域见证阈值约束、计算证明与 PoW 出块权语义严格独立 | 真实 Docker/WASM 沙箱执行隔离性假设 |
| ZKN v2 隐私与所有权 | `shielded_ownership.py` | `Privacy.lean`: Key Image / Nullifier 唯一性防双花、Note 生命周期约束、隐匿转账拆分总价值守恒 | Ristretto255/MLSAG 底层零知识密码学假设 |
| Content Fabric 内容网络 | `content_fabric.py` | `ContentFabric.lean`: CID 哈希完整性、篡改分块严格拒绝、跨节点副本数据一致性 | P2P DHT 路由表毒化与 Sybil 防护假设 |

## 这轮发现并修复的问题

1. 空/单元素 Merkle 列表没有检查目标存在；缺字段产生的 JSON null 还可能被当作相等字符串接受。
2. IBC 把区块内容 hash 当作交易 Merkle root，并对简化 header JSON 重新哈希，均与区块实际哈希规则不符。
3. 连接旧锚的任意新块可以自行构造，父哈希链不是新区块共识证明。
4. 包含性证明没有绑定中继消息的实际载荷；现在检查源交易原始字节的 hash、目标链、类型和载荷。

修复后的 `CORIUM_IBC_CHECKPOINT_V2` 使用真实区块内容 hash，并从已信任检查点
回溯历史。它拒绝旧格式及仅能链接旧锚的未来块，不自动提升信任锚。保留数据库中
`BUILT_IN:hash-chain-v1` 名称作为兼容注册标识；治理需要独立提供有效检查点。
此行为改变是为消除无认证的信任锚推进，不代表新增了共识协议。

## 验证

`bash formal/check.sh` 固定 Lean 4.19.0，检查三个文件、全部定理的公理依赖及源码漂移。
不接受 `sorry`、`admit`、自定义公理或 native 计算引入的额外公理。

`.github/workflows/formal.yml` 在 push/PR/手动触发时重新安装相同版本并运行同一入口。
新增 `test_formal_alignment.py` 已接入 `test_core_regression.sh`，由原有四组 CI 矩阵运行。
使用真实生产函数、SQLite、JSON/base64 和 SHA-256，覆盖正常路径、奇数层、缺失目标、
格式损坏、检查点/链路错误和消息替换。

最初八个新增回归在本地运行通过；用户要求重量级测试交给 CI 后，不再在本地跑
完整产品测试。最后提交的测试与源码结果以该提交的 CI 为准。
