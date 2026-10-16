# Corium v108：补全、加固与验证

源码仍为单一 `corix_v108.sh`，版本保持 108。没有新增产品命令、网络消息类型或产品子系统；原生中文 + English UI 及第三语言模板机制保留。源码明确声明的 PoW placeholder、P2P simulator 与 genesis signature bootstrap 设计未被改成另一种共识设计。

本报告区分已完成的真实回归、环境阻塞与尚未覆盖的场景。测试绿色不能代替全部生产环境验证；没有将 BLOCKED 计为 PASS。

## 修复的实际问题

| 范围 | 修复与验证 |
|---|---|
| Phoenix | 从有效历史重新重放全部链上派生表；损坏的局部派生状态不影响恢复结果。恢复保留 validator 状态、last_block、jail 元数据及协议 GPG authority。重复恢复、再次导出、无效锚点、重复字段、错误签名、缺失历史与重组组合均有回归。 |
| 规范哈希 | 修复文本与同名本地文件混淆：交易、区块、身份、CBB 与其他规范文本显式按文本计算 SHA256。实际复现过同名文件使有效交易失败；回归通过且保留原文件哈希接口。 |
| 状态纠正 | 消除批处理预扫描与正式执行的重复应用；修复传入 JSON 层级；参数绑定及表/字段白名单防止 SQL 注入；无效操作使整批失败。真实 GPG 签名的增量执行、fresh replay 和 Phoenix authority 恢复相互比较。 |
| CBB / Exodus | 绑定作者、规范消息、时间戳及签名；校验本地缓存记录，拒绝伪造、重复/过期/超大及错误密钥消息。SSPO/SNSO 校验实际存储签名、签名者身份和权益 quorum，伪造的本地 notarization 不能进入恢复交接。 |
| 链同步 / reorg | 修复读取错误数据库的处理高度、stage 交易字段/PEM 顺序、只按高度选链与没有共同祖先的同步；统一使用真实重组验证器。失败与 TERM 中断恢复三个数据库，重启后可再次同步；比较全表语义状态及 fresh replay。 |
| 验证者 / 治理 | 下一验证者查询改为只读预览，避免查询时提前执行安装或治理变更。计划变更按确定顺序执行；mining、reorg、replay 在签名与权重检查前使用同一生效边界。修复治理提案/投票误落入动态应用路径；native proposal → vote → mine → replay 已验证。 |
| 包管理 | 修复关联缓存的错误变量类型、元数据函数覆盖调用方变量、空白路径与远程仓库构建文件查找、错误版本/槽位路径、adopt 所有权/路径/根目录校验及非交互输入。安装绑定实际二进制归档，重复已发布版本不再产生第二条注册或错误 hash。 |
| 包事务 | 安装/升级失败恢复文件、world、安装记录及数据库；rollback 复用真实签名/归档/依赖/所有权检查的原生安装事务。损坏 rollback 缓存及失败 pre-remove hook 保留完整已安装版本。autoremove 使用完整已安装依赖图。 |
| 应用模板事务 | 缺少或损坏的实际包、签名、安装与 SQL migration 失败明确中止区块。模板文件及安装记录加入原有事务日志，SQL 部分成功后失败也恢复文件和数据库。scratch replay 使用私有目录。 |
| P2P / 对象 | 补齐既有 STORE、ANNOUNCE_BLOCK 及 `/chunk/<hash>` 的接收/服务路径；没有增加 wire 消息类型。校验发送者绑定，去重，持久化 provider，验证 local chunk 的 offset/size/hash。支持真实 TLS 二进制 GET/Range/续传，损坏响应不覆盖原目标；固定 TLS pin 在失败时保留。修复 IPv6/旧地址解析及调用方返回码处理。 |
| Forum | 修复 topic/post 识别、JSON/Unicode/附件名转义、manifest 路径及整对象发现；签名或公钥缺失时失败关闭。DB 缺失、object 缺失及 manifest 缺失可从有效对象重建；旧 v108 带换行 PEM author 与旧帖子空白签名保持兼容，不放宽 canonical node identity 校验。 |
| 身份 / ACL / 内容 | 修复 poisoned identity cache、agent key/hash 绑定、权限升级及成员退出边界；无权限操作失败。治理完整 PEM、重复投票、时间窗口与权益整数边界有实际数据库回归。 |
| 备份 / 快照 / Shell | SQLite 一致性备份与语义恢复、重复恢复、损坏归档拒绝、rsync snapshot rollback；归档 traversal/symlink/duplicate、文件父目录 symlink、嵌套事务及 SQL 整数边界回归。改善 EXIT/RETURN trap、quoting、临时文件与错误码消费。 |
| DApp 沙箱 / API | 修复 `_internal_run_dapp_sandboxed` 内置引擎 `runner.py` 仅注入 `request` 而缺失 `api` 对象的调用链缺口。向 RestrictedPython 受限环境注入工作状态的 `SandboxAPI` 实例及完整安全守卫（`_getitem_`、`_getiter_`、`_getattr_`、`_write_`），支持本地数据保险库读写（挂载至 `/data`）与核心 IPC 桥接；补充原生集成回归测试。 |

## 测试方式与结果

最终完整测试状态在 `validation_logs/` 中，以 `summary.tsv` 为准。早于最终源码的中断/失败运行未计入最终通过结果。

最终源码与所有 15 个测试/辅助文件的 SHA256 均与最后一次全量运行记录一致；没有在全量运行后修改实现或测试。源码 SHA256：

`38414ff466b1db14dbeaa8a23a9636a89f83f9d378cb2322f1ab46f08f6c2b1b`

| 检查或套件 | 原始环境 | 真实 SQLite 引擎补充环境 |
|---|---|---|
| 全部 11 个 Shell 文件 `bash -n` | PASS | 同一份源码 |
| `test_call.sh` | PASS | PASS |
| `test_command_surface.sh` | PASS，40 个现有 command family | PASS |
| `test_functional_smoke.sh` | BLOCKED，init 依赖缺失 | BLOCKED，init 依赖缺失 |
| `test_core_regression.sh` | BLOCKED，缺官方 sqlite3 CLI | PASS，49 个场景 |
| `test_phoenix_adversarial.sh` | BLOCKED，缺官方 sqlite3 CLI | PASS，25 个场景 |
| `test_phoenix_chaos.sh` | BLOCKED，缺官方 sqlite3 CLI | PASS，3 个场景、16 轮 |
| `test_reorg_exhaustive.sh` | BLOCKED，缺官方 sqlite3 CLI | PASS，9 个场景 |
| `test_soak_long_running.sh` | BLOCKED，缺官方 sqlite3 CLI | PASS，seed=108、16 轮混合操作 |
| 全量汇总 | 2 PASS / 6 BLOCKED / 0 FAIL，退出 77 | 7 PASS / 1 BLOCKED / 0 FAIL，退出 77 |

原始环境日志位于 `validation_logs/standard/`；补充运行日志位于 `validation_logs/supplementary/`。`validation_logs/static.json` 记录语法检查与源码/测试哈希，`validation_logs/dependencies.json` 记录真实依赖版本和缺失项。回归复现证据位于 `validation_logs/regressions/`，包含规范文本哈希 bug 修复前的失败与修复后的通过，不参与最终全量计数。

修正了测试本身的一处错误：链状态的 canonical JSON 排序不等于区块高度排序，原测试按列表末项选择最新块会随随机密钥出现误报。现改为按最大 height 选择，且明确同时断言 height=1 与 weight=1000；没有放宽产品验证或测试断言。

直接执行的 32 段内嵌 Python 编译通过，5 个 Python 测试文件语法通过。80 个不同 Python 测试场景分布为 core 49、gateway 21、reorg 9、mixed soak 1；各 Shell 包装套件会重复执行部分场景，这不是覆盖率百分比。

- 测试调用真正的 monolith、SQLite 引擎、OpenSSL/GPG 签名验证、cryptography secp256k1、实际文件事务和 TLS gateway。
- 当前机器缺少官方 sqlite3 CLI。补充运行只在 scratch PATH 中使用 Python 标准库真实 SQLite 的 CLI driver，执行真实 SQL、事务、backup/dump；该 driver 不随项目交付，不是官方 CLI 验证。
- GPG fixture 是真实 RSA OpenPGP 密钥/签名，验证由系统 GPG 完成；不依赖当前环境禁止的 gpg-agent socket。
- 混沌/soak seed=108，最终均设置 16 rounds。混合操作包含 package、forum、Exodus/CBB、挖块、backup/restore、对象、DB rollback 与 Phoenix replay。每一步比较完整 typed semantic tables、恢复 state/root 及三个 DB integrity_check；失败打印 seed、操作序列、失败断言和实际 DB 状态。
- reorg 包含 0-depth、单块、多块、较深及重复分支、等权拒绝、等高较重分支、非法签名/重复/缺失交易、半途失败、TERM 中断与重启，以及真实 peer sync、公告与 Phoenix 锚点交互。

复现入口：在正常安装依赖的环境运行 `bash test_all.sh`；可用 `CORIUM_TEST_LOG_DIR` 指定日志目录，`CORIUM_TEST_SEED`、`CORIUM_CHAOS_ROUNDS`、`CORIUM_SOAK_ROUNDS` 控制随机种子/轮数。BLOCKED 的退出码为 77。

## 环境限制与未完成的验证范围

**具体环境阻塞：** 官方 sqlite3 CLI、bc、xxd、ShellCheck 缺失；Python stun/pystun3、miniupnpc、RestrictedPython、sqlparse、psutil 缺失。原生 bwrap namespace 和 gpg-agent socket 被当前执行环境禁止。不能据此宣称 init、原生 sandbox build 或 Mod 的整条链已通过。

**尚未完成的生产验证：** 实网多 peer STUN/NAT/hole punching/relay、Tor/I2P；GIMPS/全部 compute engine 的原生执行；external package manager / Strata 的完整生命周期；Btrfs/ZFS；Wiki/Nomen/Mail/Social 的全部权限及对象组合；应用模板自定义 migration schema 与 Phoenix 的完整组合；SIGKILL/断电、磁盘满与持久化崩溃恢复。部分是覆盖缺口，不能全部归因为外部依赖缺失。

现有依赖解析、签名 binary install/remove/upgrade/rollback、adopt、autoremove、world/ownership/cache 和事务已完成这里列明的回归；源码构建、rebuild、全部 slot/ABI 冲突及外部集成不能仅凭这些测试宣布全面生产验证通过。

源码无普通 TODO/FIXME/stub/mock 实现标记；仅保留文件头明确声明的设计机制。这一静态检索不是所有函数、CLI、表、协议及边界都已穷尽的证明。
