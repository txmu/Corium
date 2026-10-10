# GitHub Actions 覆盖审计

以 VALIDATION_STATUS.md 和实际测试脚本为依据；历史报告不是本次 CI 的结果。
本地不执行测试、语法检查或测试模块导入，所有执行验证仅在 Actions。

## 已纳入自动化

- 原有八个 Shell 套件全部运行，涵盖 core、gateway、reorg、Phoenix、混合 soak；退出 77 会使 job 失败。
- Ubuntu 22.04 / 24.04 × seed 108 / 2026，chaos 和 soak 均为 16 轮。
- 官方 sqlite3 CLI 与全部 init Python/系统依赖，解除原报告的依赖阻塞。
- 所有 Shell 语法、Python 文件及直接调用的内嵌 Python 编译；源码和测试 SHA256 留档。
- ShellCheck 全量报告留档。现有单体脚本未建立零告警基线，所以当前报告不作为阻断门禁。
- 新增真实 bubblewrap C 编译、空白路径、只读系统及宿主文件隔离、超时失败。
- 新增 Wiki 不存在页面拒绝且状态不变、Mail 删除参数 SQL 注入及数据库完整性回归。
- push、PR、手动与每周定时触发；失败仍上传日志，每个矩阵任务独立产物。

## 仍未穷尽的场景（不能宣称全部覆盖）

| 缺口 | 需要补充的验证资源/场景 |
|---|---|
| 实网 STUN/NAT/hole punching/relay、Tor/I2P | 多主机、不同 NAT 拓扑、可控 STUN/relay/Tor/I2P 服务；现有 TLS peer 是环回真实协议测试 |
| 全部 compute engine / GIMPS | 各引擎实际安装与小型可验证任务；sandbox 编译不代表 compute 生命周期 |
| Strata / 外部包管理器 | 隔离 VM 中真实 debootstrap/pacstrap/dnf 等创建、执行、导出、升级及销毁 |
| Btrfs/ZFS | 专用磁盘/loopback 后端与创建、回滚、删除、失败恢复测试；现有快照只验证 rsync |
| Wiki/Nomen/Mail/Social | 完整身份、群组权限、对象、版本、加密邮件与 replay 组合；新增负向测试仅覆盖其中两个边界 |
| 模板自定义 migration + Phoenix | 多 schema 的升级/失败/重放/恢复交叉测试；现有固定 schema 事务场景不能替代 |
| SIGKILL/断电/磁盘满 | 故障注入及重启后数据库和文件事务一致性；现有 TERM 回滚不能替代 SIGKILL |
| build/rebuild、slot/ABI | 完整签名源码包发布、安装、rebuild 和 slot/ABI 冲突矩阵；原生 sandbox 编译只验证构建执行环境 |

这些缺口没有用 mock、依赖探测或“预期失败”充当通过结果。完整生产矩阵仍需新增专门夹具和测试。
