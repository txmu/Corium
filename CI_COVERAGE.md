# GitHub Actions 覆盖审计

重量级产品测试在 GitHub Actions 执行；本地允许 Lean 和语法检查。
本轮新增八个针对性回归曾在本地通过，之后的完整测试以 CI 为准。
历史 `VALIDATION_STATUS.md` 不能替代当前运行日志。

## 原有测试

`validation.yml` 运行全部八个 Shell 套件（core/gateway/reorg/Phoenix/soak），
Ubuntu 22.04 / 24.04 × seed 108 / 2026，chaos/soak 各 16 轮。
官方 sqlite3、真实 OpenSSL/GPG、TLS、Python cryptography 和系统依赖均安装。
core 入口额外运行 `test_formal_alignment.py`，覆盖修复后的 Merkle/IBC 检查点证明。
独立 `formal.yml` 固定 Lean 4.19.0，重跑全部证明、公理审计与源码映射漂移检查。
全部 Shell 语法、项目与 ci Python、直接执行的内嵌 Python 编译在 CI 验证。
ShellCheck 为非阻断报告，有内存/超时上限，超限不是通过。

## 剩余八类均已接入

新 workflow：`.github/workflows/remaining-coverage.yml`。25 个执行任务和一个汇总门禁，
push、PR、手动及每周触发；`fail-fast: false`，失败不阻止其他类别运行。
任何执行失败、环境阻塞、取消或跳过均使最终门禁失败。没有 expectedFailure 或 skip。

| 原缺口 | 实际测试入口 | 环境和断言 |
|---|---|---|
| STUN/NAT/hole punching/relay、Tor/I2P | `ci/test_network.py`、`ci/test_anonymous.py` | 三个独立生产 TLS peer、双子网 Linux namespace、路由器 SNAT/防火墙、coturn、miniupnpd；直连、签名 STORE、阻断后中继、反向打洞信令、STUN 公网地址、三端口 UPnP；真实 Tor onion/I2P destination 通道与错误 TLS pin 拒绝，保留 pcap/服务日志 |
| compute/GIMPS | `ci/test_compute.py` | 所有现有引擎分支：Engine Zero 独立求 nonce/绑定/提交、GIMPS 指数推进/耗尽及 sandbox Lucas-Lehmer、通用 Mod 的真实可执行程序/清单/调度/执行、无效证明拒绝 |
| Strata/外部 PM | `ci/test_strata.py`、`ci/test-external-pm.sh` | apt/pacman/dnf/portage 四类原生 create、真实 distro rootfs 中安装/查询/导出/提升/重建/卸载/销毁；九类外部导入 apt/pacman/dnf/portage/xbps/zypper/pkgsrc/pip/npm，与真实包名/版本匹配且重复导入一致 |
| Btrfs/ZFS | `ci/test_filesystems.py` | 专用 loopback 文件系统/池，真实 subvolume/dataset；产品创建必须选中该后端，禁止悄悄降级 rsync；独立参考快照测试回滚、配置/DB 恢复、实际删除、损坏元数据拒绝 |
| Wiki/Nomen/Mail/Social | `ci/test_apps.py` | 群组策略、邀请/踢出/权限、Wiki 对象/附件/版本/锁/冲突、Nomen 注册/解析/转让/所有权/无效域名、RSA 真实 E2EE 与错误密钥、原生身份私信与附件、邮件列表明文/归档/删除；成功路径与 replay/Phoenix 比较 |
| migration/Phoenix | `ci/test_templates.py` | 真实签名模板包；自定义 TEXT/BLOB/约束 schema、版本升级 migration、失败和错误签名原子回滚；fresh replay/Phoenix 后自定义表逐行比较，不能只比较内置表 |
| SIGKILL/断电/磁盘满 | `ci/test_faults.py`、`ci/power_guest.py` | 实际生产事务中 SIGKILL 后重新调用恢复；192 MiB ext4 实际 ENOSPC 下 SQL/包事务失败并验证原状态；QEMU 未提交/已提交检查点直接 SIGKILL 整个 VM，再冷启动比较文件/world/三个真实 DB 完整性与语义状态 |
| build/rebuild/slot/ABI | `ci/test_packages.py` | 小型 C 源码真实构建、发布、真实 GPG archive 签名、安装/重建/移除；不同槽位共存、文件冲突原子性、slot/subslot 依赖、篡改源 checksum 拒绝 |

## 结果解读

“接入 CI”表示上述具体场景有实际可执行测试，**不等于已经通过**。
新测试可以揭示产品错误；不通过删除断言、mock 服务端、替换加密验证器或跳过场景使结果变绿。
基础设施安装、公共 Tor/I2P bootstrap、发行版仓库不可用时仍失败，并保留日志。

受控 NAT 是真实内核网络拓扑，但不能代表互联网所有运营商的 NAT 类型。
断电测试覆盖两个事务检查点，不代表所有 CPU 指令间的断电窗口。
通用引擎是实际算法夹具；仓库没有交付的第三方计算程序不能宣称全部已验证。
四种 Strata、九种外部导入覆盖现有源码分支，未来新增分支需要新增矩阵项。

运行结果以两个 workflow、各 job 日志和 artifacts 为准。日志留存 14 天。
