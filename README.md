# Corium

Corium v108 单文件 Bash 实现，入口为 `corix_v108.sh`。

## 自动化验证

[GitHub Actions](https://github.com/txmu/Corium/actions/workflows/validation.yml) 在 Ubuntu 22.04 和 24.04 上运行全部既有测试套件，以及新增原生 sandbox 与应用边界回归。两组固定随机种子为 108、2026，chaos/soak 各 16 轮。

每次 push、PR、手动触发和每周一运行。测试退出 77（BLOCKED）与非零失败都使任务失败；日志、汇总和文件哈希作为 artifact 保留 14 天。ShellCheck 是非阻断审计报告，限制 2 GiB 内存和 3 分钟执行时间；超限退出码也会写入任务摘要，不能将其视为静态检查通过。

本次建仓过程中没有在本地执行测试；真实执行结果以 Actions 运行记录为准。

## 覆盖边界

详见 [CI_COVERAGE.md](CI_COVERAGE.md)。[VALIDATION_STATUS.md](VALIDATION_STATUS.md) 是建仓前的历史报告，引用的 `validation_logs/` 未包含在原始交付目录中，其历史结果不能作为本次 CI 结果。

原审计剩余八类现在均有独立 CI 入口：[剩余覆盖 workflow](https://github.com/txmu/Corium/actions/workflows/remaining-coverage.yml)。包括真实网络/匿名网络、现有计算引擎分支、四类 Strata 和九类外部包管理器、Btrfs/ZFS、应用权限/对象/重放、模板 migration/Phoenix、SIGKILL/ENOSPC/QEMU 冷启动及源码构建/slot/ABI。具体边界、断言与状态见覆盖审计；接入不等于通过。

源码声明的 PoW placeholder、P2P bootstrap simulator 和 genesis signature bootstrap 保留原设计；测试通过不代表所有生产场景已验证。
