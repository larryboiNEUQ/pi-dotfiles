# Maintainer notes

本文件给**仓库维护者**（作者或 fork 后自己维护清单的人）用，不是冷启动访客文档。访客请看根目录 [README.md](../README.md)。

## 工具方向

| 方向 | 脚本 | 作用 |
|------|------|------|
| 仓库 → 机器 | `scripts/install.sh` / `scripts/quick-install.sh` | 按 `packages.json` 安装远程包，拷贝本地 extensions / configs / agents；可选 `--with-settings` |
| 机器 → 仓库 | `scripts/dump.sh` | 从本机 Pi 配置写回 `packages.json`；`--sync-locals` 再同步 plan-mode / footer-no-model / spark.json / pi-fff.json / agents |

## 多机同步循环

在**改过插件 / agents** 的机器上：

```bash
cd ~/.pi-dotfiles   # 或本仓库路径
./scripts/dump.sh --sync-locals
# 检查 packages.json（及 extensions/、agents/）diff
git add -A && git commit -m "sync: update pi packages from machine" && git push
```

在**另一台机器**上：

```bash
cd ~/.pi-dotfiles && git pull && ./scripts/install.sh
# 或
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash
```

需要作者主题 / 默认模型时再加 `--with-settings`（见 README 选项 B）。

## dump 做什么

`dump.sh` 会：

1. 读 `~/.pi/agent/settings.json` 里的 `packages`
2. 用 `~/.pi/agent/npm/package.json` 钉住已装 npm 版本
3. 写回仓库 `packages.json`（保留已有 note、local_extensions、local_configs、local_agents）
4. 若带 `--sync-locals`：把本机下列路径拷回仓库：
   - `~/.pi/agent/extensions/plan-mode` → `extensions/plan-mode`
   - `~/.pi/agent/extensions/footer-no-model.ts` → `extensions/footer-no-model.ts`
   - `~/.pi/agent/spark.json` → `configs/spark.json`
   - `~/.pi/agent/pi-fff.json` → `configs/pi-fff.json`
   - `~/.pi/agent/agents/*.md` → `agents/`

然后自行 commit / push。

`install.sh` 会安装 `local_extensions`（目录或单文件）与 `local_configs`（如 `spark.json`）。

## 不要提交

与公开 README 一致，永远不要把这些放进仓库：

- `auth.json`、API keys、tokens
- `models-store.json`
- sessions、logs

`settings.partial.json` 只允许非密钥偏好（主题 / 默认模型 / thinking）。

## 关于 templates

`--with-templates` 与 `templates/` **已移除**。  
`pi-auto-review` 使用包内默认（`authorizerChain: ["safe-allow"]`，评审超时等见该仓库 README / 默认配置），dotfiles 不再分发 permission config 文件。

若本机曾手写 `~/.pi/agent/extensions/pi-permission-*/config.json`，与包默认冲突时以本机文件为准；不再需要时可删除以完全走包默认。
