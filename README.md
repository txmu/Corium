# Corium

Corium v108 单文件 Bash 实现，入口为 `corix_v108.sh`。

## Ziokt 原生接入

`corix ziokt capabilities` 查看默认关闭的本地联邦契约。所选网络的
`corix.conf` 新增 `[ziokt]` 段，使用 `enabled = TRUE`、`federation_id`、
`provider_id` 和 `allow_mutations = FALSE`；配置文件必须为当前用户所有、
非符号链接、模式 `0600`。`corix ziokt --network NAME rpc --stdio` 使用固定、
有界操作表。只读入口在原生建锁目录、恢复和交互之前分流，不写盘。
写操作还须启用 `allow_mutations=TRUE` 并配置动作、资源允许列表；固定
Wiki、Strata、快照、原生挖块、内容及 Phoenix 恢复使用持久化意图与幂等日志。
`transport_bindings_file` 可将原生 `dht_send_message` 接入 Shadow6 原始 SDK；
对端身份和部署锁须固定，直连回退仅按显式策略执行。配置不存在或为 FALSE

全部实现内嵌在生产文件，独立交付不依赖 Ziokt 仓库。普通原生命令与
sourced API 保留既有行为。对象目录包含软件包、Strata、应用、身份、名称、提案和快照元数据，
不将存储记录声明为运行健康。运行 `python3 -m unittest -v test_ziokt`
验证独立交付、关闭模式、网络作用域、协议拒绝和无恢复副作用。

## 自动化验证

[GitHub Actions](https://github.com/txmu/Corium/actions/workflows/validation.yml) 在 Ubuntu 22.04 和 24.04 上运行全部既有测试套件，以及新增原生 sandbox 与应用边界回归。两组固定随机种子为 108、2026，chaos/soak 各 16 轮。

每次 push、PR、手动触发和每周一运行。测试退出 77（BLOCKED）与非零失败都使任务失败；日志、汇总和文件哈希作为 artifact 保留 14 天。ShellCheck 是非阻断审计报告，限制 2 GiB 内存和 3 分钟执行时间；超限退出码也会写入任务摘要，不能将其视为静态检查通过。

本次建仓过程中没有在本地执行测试；真实执行结果以 Actions 运行记录为准。

## 覆盖边界

详见 [CI_COVERAGE.md](CI_COVERAGE.md)。[VALIDATION_STATUS.md](VALIDATION_STATUS.md) 是建仓前的历史报告，引用的 `validation_logs/` 未包含在原始交付目录中，其历史结果不能作为本次 CI 结果。

原审计剩余八类现在均有独立 CI 入口：[剩余覆盖 workflow](https://github.com/txmu/Corium/actions/workflows/remaining-coverage.yml)。包括真实网络/匿名网络、现有计算引擎分支、四类 Strata 和九类外部包管理器、Btrfs/ZFS、应用权限/对象/重放、模板 migration/Phoenix、SIGKILL/ENOSPC/QEMU 冷启动及源码构建/slot/ABI。具体边界、断言与状态见覆盖审计；接入不等于通过。

源码声明的 PoW placeholder、P2P bootstrap simulator 和 genesis signature bootstrap 保留原设计；测试通过不代表所有生产场景已验证。
