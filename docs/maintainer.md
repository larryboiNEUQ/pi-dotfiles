# 维护 Pi 全局配置

本说明面向配置所有者和仓库维护者。访客安装入口见 [README](../README.md)。术语见 [CONTEXT.md](../CONTEXT.md)，同步设计见 [设计记录](plans/sync-design.md)。

## 执行边界

本轮开发只授权仓库修改和隔离验证。没有授权在真实 Pi 上安装、应用、卸载或清理，也没有授权提交或推送。以下命令说明后续使用方式，不代表本轮已经执行。

## 检查本机与仓库差异

```bash
	python3 scripts/sync.py audit
	python3 scripts/sync.py audit --public
```

审计不创建文件，不写同步基线，不调用插件升级。诊断只输出纳管项标识或未知名称，不输出未知值。待分类项显示覆盖不完整。

审计发现新字段后，先决定纳管、排除或外部所有权，再修改清单。工具不因发现一个字段就自动导出它。

## 导出本机修改

```bash
	./scripts/dump.sh --dry-run
	./scripts/dump.sh
	git diff
```

导出同步全部纳管参数和资源，不需要旧 `--sync-locals` 开关。npm 来源不带版本，Git 使用清单声明的分支。导出不升级插件，不拉取 Git，不提交，不推送。

首次没有同步基线时，仓库已有不同值需要确认。后续仓库单侧修改不会被本机旧值覆盖。缺失的本机字段或文件不删除仓库内容。

检查 diff 后，由你单独决定是否提交与推送。不要使用无检查的 `git add -A` 把未知文件带入公开仓库。

## 在另一台机器应用

先单独更新仓库。配置同步本身不运行 Git pull。

```bash
	git pull --ff-only
	./scripts/install.sh --dry-run
	./scripts/install.sh
```

只同步参数时使用 `--skip-packages`。访客使用 `--public`。

```bash
	./scripts/install.sh --skip-packages
	./scripts/install.sh --skip-packages --public
```

必要确认在第一项写入或插件操作之前收齐。无交互且需要确认时非零退出。工具不提供默认覆盖的 `--prefer repo` 或 `--prefer local`。

## 处理冲突

工具相对本机同步基线比较两侧内容。JSON 按纳管叶字段比较，数组与文本按整体比较。两侧修改同一项且结果不同构成冲突。

单侧修改只向另一侧传播。应用保留本机单侧修改，导出保留仓库单侧修改。只有两侧实际相同的成功项才能推进共同基线。

冲突发生时整批暂停，插件升级也等待。检查冲突标识，并在终端逐项选择结果。不要删除基线来掩盖冲突。

确认提示标注目标侧与输入侧。公共标量显示批准字段的值，公共文本显示有长度限制的 diff。个人参数、权限和账号相关内容显示摘要，不打印秘密或未知字段。

## 保留秘密和外部内容

LangSmith 只导出 `enabled`、`api_url` 和 `project`。应用保留本机 `api_key`。新增 reader 支持不等于自动纳管。

pi-pstack 拥有 `comment-sicko.md`、`poteto-agent.md`、`pstack-readonly.md`、`pstack/models.md` 和 `pstack/subscriptions.md`。本仓库不覆盖或删除它们。它们的个人设置不会由本仓库迁移。

权限规则的匹配顺序有语义。不要为美化 diff 对规则排序。goal 过期字段只提示清理，不自动删除。

## 更新插件来源

只有安装和更新命令执行升级。Git 插件目录存在本地修改时停止，先自行处理修改再更新。声明分支不存在时停止，修改清单后再运行，不自动切到默认分支。

npm 不固定版本。不要把已安装版本重新写回来源。清单是来源声明，不是历史锁文件。

Git 来源和 ref 是独立纳管单位。两侧都修改分支时先解决冲突。如果安装时选择保留与仓库不同的本机分支，安装停止，提示先导出该来源修改；不会随后把它静默覆盖。参数应用只提示来源变化待安装，不改 checkout 或注册来源。

`branch` 是选定跟随分支，`defaultBranch` 是已核实的上游默认分支。两者不能混用，本机未指定 ref 的来源按明确记录的默认分支比较。没有该记录时，工具不猜默认分支。

`legacyRefs` 只登记批准迁移的旧固定 ref。本仓库仅登记 auto-review 的 `v2.4.0`。没有来源基线时，安装可按已批准策略改为声明分支，导出仍不把旧 tag 当作分支。建立来源基线后，再出现旧 ref 就按普通修改处理，不继续静默归一化。

## 删除与恢复默认

从清单移除一项表示退出纳管，不修改本机。机器中缺失一项也不表示删除。

删除记录表达三种操作。

- 恢复默认只移除指定参数覆盖。
- 文件删除只作用于指定纳管文件。
- 插件卸载只作用于指定纳管插件。

记录使用稳定标识并保留到所有者明确清理。每台机器分别确认操作，晚同步机器仍读取该记录。已经不存在的目标是无操作，不恢复、不误删未知内容。

删除记录放在 `packages.json` 的 `removals` 数组中。以下是三种记录的格式示例，不是建议执行的清理。只添加你明确需要的记录，并保留目标的纳管声明。

```json
	{
	  "removals": [
	    {"id": "reset-theme-v1", "action": "restore-default", "resource": "settings", "field": "/theme"},
	    {"id": "delete-worker-v1", "action": "delete-file", "resource": "agent-worker"},
	    {"id": "remove-tps-v1", "action": "uninstall-package", "resource": "pi-tps-meter"}
	  ]
	}
```

先运行 `python3 scripts/sync.py apply --dry-run` 查看对象，再在终端运行 `python3 scripts/sync.py apply`。插件卸载是显式删除操作，因此参数应用入口只有在存在并确认卸载记录时才调用 `pi remove`，不会调用安装或升级。

同一个记录标识不能复用为另一种操作。恢复配置时自行清理对应记录，否则晚同步机器仍会收到删除要求。不得为方便删除而把外部拥有项临时改成纳管项。

## 执行失败

插件失败后立即停止，报告已完成和未尝试项。已成功升级插件仍保留，配置回滚不等于插件回滚。

配置写入前备份。配置事务发生可捕获失败时，恢复本批已写配置。并发修改或恢复失败必须明确报告，不假装回滚完成。基线不记录失败或已回滚项。

审计和 dry-run 不创建备份。备份在仓库外，不入库。不可捕获的进程终止与崩溃恢复只按实际测试证据声明，不从普通异常回滚推断。

## 重跑隔离验证

```bash
	python3 -m unittest discover -s scripts/tests -v
	bash -n scripts/install.sh scripts/dump.sh scripts/quick-install.sh
	python3 scripts/sync.py --help
```

测试使用临时 HOME、临时 agent 目录和假 Pi、Git。它从用户命令入口断言结果，不在真实 HOME 运行安装或应用。

验证报告见本轮交接记录。没有跑过的真实网络升级、生产权限错误或崩溃边界必须标为未验证。

## 维护规格与实施票

GitHub 是权威 tracker。配置见 [issue tracker](agents/issue-tracker.md)。本地 `.scratch/` 只保留草稿、迁移脚本和远端索引。

规格是 [#2](https://github.com/larryboiNEUQ/pi-dotfiles/issues/2)。实施票从 [#3](https://github.com/larryboiNEUQ/pi-dotfiles/issues/3) 到 [#7](https://github.com/larryboiNEUQ/pi-dotfiles/issues/7)，按原生 blocking 关系顺序执行。未经实际验证，不关闭票，也不把后续票视为已解除阻塞。
