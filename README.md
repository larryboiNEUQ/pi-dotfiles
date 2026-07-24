# pi-dotfiles

作者在用的 [Pi coding agent](https://pi.dev) 插件 / 扩展配置，公开分享——拿去用即可。

A shared Pi plugin setup (packages + plan-mode + agents). Install with one command.

## 前提

```bash
npm install -g @earendil-works/pi-coding-agent
pi --version   # >= 0.81
```

## 安装

二选一（给人或 agent 直接复制命令）。

### A. 默认（推荐）

只装插件 + 本地 extension / agents，**不**改主题与默认模型：

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash
```

或 clone 后：

```bash
git clone https://github.com/larryboiNEUQ/pi-dotfiles.git ~/.pi-dotfiles
cd ~/.pi-dotfiles && ./scripts/install.sh
```

### B. 附带作者偏好（可选）

在 A 的基础上，把 [`settings.partial.json`](./settings.partial.json) 合并进 `~/.pi/agent/settings.json`（主题 / 默认 provider 与 model / thinking 级别）。**不碰** auth、API keys、sessions。插件与 auto-review **不依赖** 本选项。

具体键值以 `settings.partial.json` 为准（勿在文档里猜模型名）。

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash -s -- --with-settings
```

或：

```bash
./scripts/install.sh --with-settings
```

安装前可 dry-run：

```bash
./scripts/install.sh --dry-run
```

## 装了什么

版本与完整清单见 [`packages.json`](./packages.json)。

### 编辑与子代理

| 包 | 作用 |
|----|------|
| `pi-hashline-edit` | 按 hash 锚定的行编辑辅助 |
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

### 本地扩展与 agents

| 资源 | 作用 |
|------|------|
| `plan-mode` | 官方 plan 模式（`/plan`，快捷键见扩展说明） |
| agents | Explore / Plan / Worker / general-purpose 子 agent 定义 |

## 装完验证

```bash
pi list
# 新开 pi 会话
/login              # 需要时配置模型鉴权
/mcp setup          # 若用 pi-mcp-adapter
/plan               # plan-mode
# 正文中间输入 $skill名  → inline skill 补全
/gallery            # 有图时
```

## 安全

- 第三方 Pi package 拥有本机完整权限；只装你信任的源（见 `packages.json`）。
- **不会**入库：`auth.json`、API keys、`models-store.json`、sessions、logs。
- 新机仍需自行 `/login` 与各服务密钥配置。

## License

MIT（`extensions/plan-mode` 来自 `@earendil-works/pi-coding-agent` examples，遵循其原仓库许可。）

---

维护者多机同步（dump / 回写）见 [docs/maintainer.md](./docs/maintainer.md)。
