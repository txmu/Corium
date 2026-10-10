# Corium

Corium v108 单文件 Bash 实现，入口为 `corix_v108.sh`。

## 自动化验证

[GitHub Actions](https://github.com/txmu/Corium/actions/workflows/validation.yml) 在 Ubuntu 22.04 和 24.04 上运行全部既有测试套件，以及新增原生 sandbox 与应用边界回归。两组固定随机种子为 108、2026，chaos/soak 各 16 轮。

每次 push、PR、手动触发和每周一运行。测试退出 77（BLOCKED）与非零失败都使任务失败；日志、汇总和文件哈希作为 artifact 保留 14 天。ShellCheck 是非阻断审计报告，限制 2 GiB 内存和 3 分钟执行时间；超限退出码也会写入任务摘要，不能将其视为静态检查通过。

本次建仓过程中没有在本地执行测试；真实执行结果以 Actions 运行记录为准。

## 覆盖边界

详见 [CI_COVERAGE.md](CI_COVERAGE.md)。[VALIDATION_STATUS.md](VALIDATION_STATUS.md) 是建仓前的历史报告，引用的 `validation_logs/` 未包含在原始交付目录中，其历史结果不能作为本次 CI 结果。

实网多 peer NAT/Tor/I2P、全部 compute engine、Strata/外部包管理器、Btrfs/ZFS、完整应用权限与对象组合、模板 migration/Phoenix 交叉组合、SIGKILL/断电/磁盘满、完整 build/rebuild/slot/ABI 矩阵尚未全部实现自动化验证。

源码声明的 PoW placeholder、P2P bootstrap simulator 和 genesis signature bootstrap 保留原设计；测试通过不代表所有生产场景已验证。
