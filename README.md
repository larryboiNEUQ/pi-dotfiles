# pi-dotfiles

作者在用的 [Pi coding agent](https://pi.dev) 插件 / 扩展配置，公开分享——拿去用即可。

A shared Pi plugin setup (packages + plan-mode + agents + spark UX). Install with one command.

## 前提

```bash
npm install -g @earendil-works/pi-coding-agent
pi --version   # >= 0.81
```

## 安装

先选择插件版本策略；作者偏好设置可与任一策略组合。

### A. 固定版（默认、推荐）

按 [`packages.json`](./packages.json) 的 `source` 安装固定 npm 版本，同时安装本地 extension / configs / agents；**不**改主题与默认模型：

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash
```

或 clone 后：

```bash
git clone https://github.com/larryboiNEUQ/pi-dotfiles.git ~/.pi-dotfiles
cd ~/.pi-dotfiles && ./scripts/install.sh
```

### B. Latest 版（可选）

按 `latest_source` 安装不带版本约束的推荐插件：npm 包解析为安装时的 latest，Git 包跟随未固定 ref 的默认分支。

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash -s -- --latest
```

或 clone 后：

```bash
./scripts/install.sh --latest
```

Latest 版不可复现，插件升级可能带来兼容性变化。其安装来源会以无版本约束形式写入 Pi 设置，后续可运行：

```bash
pi update --extensions
```

重新运行不带 `--latest` 的安装命令即可切回固定 npm 版本。当前清单中的 Git 包本来就没有 tag/commit ref，因此固定版和 Latest 版对这些 Git 包使用相同来源。

### C. 附带作者偏好（可选）

在 A 或 B 的基础上，把 [`settings.partial.json`](./settings.partial.json) 合并进 `~/.pi/agent/settings.json`（主题、默认 provider / model / thinking，以及精简启动与消息队列偏好）。**不碰** auth、API keys、sessions。插件与 auto-review **不依赖** 本选项。

具体键值以 `settings.partial.json` 为准（勿在文档里猜模型名）。

包级资源过滤不属于可选作者偏好，安装器总会应用：`pine-of-glass` 保留其他观测扩展，但禁用与 Pi Calm 工具隐藏冲突的 `pi-traceline`。

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash -s -- --with-settings
# Latest + 作者偏好：末尾改为 --latest --with-settings
```

或：

```bash
./scripts/install.sh --with-settings
./scripts/install.sh --latest --with-settings
```

安装前可 dry-run：

```bash
./scripts/install.sh --dry-run
./scripts/install.sh --latest --dry-run
```

## 装了什么

固定来源、Latest 来源与完整清单见 [`packages.json`](./packages.json)。

### 编辑与子代理

| 包 | 作用 |
|----|------|
| `pi-hashline-edit` | 按 hash 锚定的行编辑辅助 |
| [`@ff-labs/pi-fff`](https://github.com/dmtrKovalenko/fff/tree/main/packages/pi-fff) | FFF 模糊文件/内容搜索；通过配置以 `find` / `grep` 同名覆盖原生工具 |
| `@tintinweb/pi-subagents` | Claude Code 风格 subagents |

### 网络与媒体

| 包 | 作用 |
|----|------|
| `pi-web-access` | 网页搜索 / fetch、GitHub clone、YouTube / PDF / 视频 |
| `pi-codex-image-gen` | Codex 图像生成 |
| `pi-gallery` | 会话图片画廊（`/gallery`） |

### Skills

| 包 | 作用 |
|----|------|
| [`pi-inline-skill-complete`](https://github.com/larryboiNEUQ/pi-inline-skill-complete) | 正文中间输入 `$name` 弹出 skill 补全，选中后插入 `/skill:name` |
| `pi-skillful` | 发送时在任意位置展开 `/skill:name`；可用 `/skillful` 管理可见性 |

示例：`请审查这段代码 $code-review` → 补全为 `/skill:…` → 发送时由 skillful 展开。

### 权限与 MCP

| 包 | 作用 |
|----|------|
| [`pi-auto-review`](https://github.com/larryboiNEUQ/pi-auto-review) | 权限系统 + 委托 safe-allow 评审（包内默认即可，无需额外 config 模板） |
| `pi-mcp-adapter` | 省 token 的 MCP 适配（约 200 token 代理） |

### 体验与工作流

| 包 | 作用 |
|----|------|
| `pi-spark` | 紧凑 editor、credits / 限流、presets、idle recap、自动 session 标题等 |
| [`pi-calm`](https://github.com/larryboiNEUQ/pi-calm) | `/calm` 切换安静展示：隐藏折叠 thinking 与内置工具外壳，保留完整执行和会话数据 |
| `pine-of-glass` | 上下文 / cache / latency 观测；通过包过滤禁用 `pi-traceline`，避免覆盖 Pi Calm 的工具隐藏 |
| `@juicesharp/rpiv-ask-user-question` | 结构化多选问卷工具 `ask_user_question`（有歧义时问你而不是瞎猜） |
| `@narumitw/pi-goal` | `/goal` 自主目标模式（`goal_complete` / `goal_blocked`） |

### 本地扩展、配置与 agents

| 资源 | 作用 |
|------|------|
| `plan-mode` | 官方 plan 模式（`/plan`，快捷键见扩展说明） |
| `footer-no-model.ts` | 原版风格 token / 金额 / 上下文 footer，**不显示**右侧模型（避免与 pi-spark 顶栏重复） |
| `configs/spark.json` | `{ "footer": false }` — 关掉 pi-spark 自带 footer，让上面的 footer 接管状态栏 |
| `configs/pi-fff.json` | 让 pi-fff 以 `override` 模式提供 `find` / `grep`，并禁用根目录与 HOME 扫描 |
| agents | Explore / Plan / Worker / general-purpose 子 agent 定义 |

## 装完验证

```bash
pi list
# 新开 pi 会话
/login              # 需要时配置模型鉴权
/mcp setup          # 若用 pi-mcp-adapter
/plan               # plan-mode
/goal <目标>        # pi-goal（若已装）
/calm              # 切换 Calm 安静展示
/fff-health         # 检查 pi-fff 索引状态
# 正文中间输入 $skill名  → inline skill 补全
/gallery            # 有图时
```

状态栏预期：

- **editor 顶栏**：`provider/model:thinking`（pi-spark）
- **footer**：`↑token ↓token $cost 上下文%` + credits 行，**无**右侧重复模型名

## 安全

- 第三方 Pi package 拥有本机完整权限；只装你信任的源（见 `packages.json`）。
- `--latest` 会随上游发布变化，稳定性与可复现性低于默认固定版。
- **不会**入库：`auth.json`、API keys、`models-store.json`、sessions、logs。
- 新机仍需自行 `/login` 与各服务密钥配置。

## License

MIT（`extensions/plan-mode` 来自 `@earendil-works/pi-coding-agent` examples，遵循其原仓库许可。）

---

维护者多机同步（dump / 回写）见 [docs/maintainer.md](./docs/maintainer.md)。
