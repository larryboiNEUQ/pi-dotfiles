# pi-dotfiles

这是作者的 Pi 全局配置仓库。默认入口恢复插件、显示与工作流参数，以及作者的个人模型、agents 和权限参数。其他使用者选择公共模式，或 fork 后修改自己的参数。

仓库公开。配置按字段白名单纳管，凭证不入库。术语见 [CONTEXT.md](CONTEXT.md)，背景决定见 [ADR](docs/adr/)。

## 安装前检查

本仓库的 npm 插件跟随安装时的最新版，Git 插件跟随清单声明的分支。清单不能重现历史安装版本。只有安装和更新会升级插件，审计、导出和参数应用不升级。

安装器需要 Pi、Python 3 和 Git。先安装 Pi，再登录需要的模型与服务。仓库不分发凭证。

```bash
	npm install -g @earendil-works/pi-coding-agent
	pi --version
```

## 恢复作者配置

先 clone 仓库。

```bash
	git clone https://github.com/larryboiNEUQ/pi-dotfiles.git ~/.pi-dotfiles
	cd ~/.pi-dotfiles
```

查看计划。dry-run 不创建目录、备份或同步基线，也不升级插件。

```bash
	./scripts/install.sh --dry-run
```

在终端执行安装。

```bash
	./scripts/install.sh
```

目标中缺失的参数可创建。目标已有且不同的参数需要确认。无交互且需要确认时，工具返回非零状态，不覆盖已有值。

## 只安装公共配置

访客使用公共模式，不导入作者的默认模型、agents、权限和 LangSmith 参数。

```bash
	./scripts/install.sh --public --dry-run
	./scripts/install.sh --public
```

一键入口只在首次 clone 或可以快进时更新仓库。已有目标不是正确仓库时停止，不删除该目录。

```bash
	curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash -s -- --public
```

一键入口没有交互终端。若工具要求确认，按输出指引在终端运行本地安装脚本。

## 只应用参数

只应用参数不安装或升级插件。

```bash
	./scripts/install.sh --skip-packages --dry-run
	./scripts/install.sh --skip-packages
```

`--public` 可与参数应用组合。旧 `--latest`、`--with-settings` 和 `--sync-locals` 不再选择另一套策略，最新版、全部参数和纳管资源同步已成为默认行为。

## 纳管内容

完整清单和当前参数以 [packages.json](packages.json) 及其指定文件为准。

| 类别 | 内容 |
| --- | --- |
| 编辑与代理 | hashline edit、FFF、subagents。 |
| 网络与媒体 | web access、Codex image generation、gallery。 |
| Skill 交互 | inline skill complete、skillful。 |
| 权限 | auto-review、权限规则和 safe-allow 评审参数。 |
| 显示与工作流 | Spark、Calm、Pine of Glass、问卷、goal、TPS meter、plan-mode、footer。 |
| 登录与追踪 | Cursor、Devin、LangSmith 插件。需要本机凭证。 |

仓库使用 Pi 内置 MCP，不安装 `pi-mcp-adapter`，也不写入 `-builtin:mcp`。这不自动迁移已有机器的 MCP 配置，也不自动卸载本机 adapter。

pi-pstack 的三个 agent 定义和两个配置文件由 pi-pstack 管理。skills、Herdr、项目级配置、凭证、设备标识、信任记录、会话、缓存、日志和安装状态不纳管。

## 同步前审计

审计只读，不升级插件。

```bash
	python3 scripts/sync.py audit
```

未知入口或字段只显示名称，不显示值。存在待分类项时，审计报告覆盖不完整。它不阻止已纳管内容同步，但也不表示全部配置已覆盖。

## 安全边界

- 第三方 Pi 插件拥有本机权限，只安装你信任的来源。
- 导出只包含清单允许的非密钥字段，应用保留未知字段和本机密钥。
- 两侧冲突在任何写入和插件升级前阻止整批操作。
- 写入前备份。配置失败时恢复本批配置，已升级插件不能回滚。
- 缺失不代表删除，删除必须使用显式记录并确认。
- Git 分支消失或插件目录有本地修改时停止，不切换分支，不丢弃修改。
- 工具不提交、不推送。项目配置由各项目自己的 Git 管理。

多机同步、删除记录和验证命令见 [维护说明](docs/maintainer.md)。规格与实施票在 [GitHub Issues](https://github.com/larryboiNEUQ/pi-dotfiles/issues/2)。

## License

MIT。`extensions/plan-mode` 来自 Pi examples，遵循原仓库许可。
