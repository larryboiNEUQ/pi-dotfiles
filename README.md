# pi-dotfiles

本机 [Pi coding agent](https://pi.dev) 插件 / 扩展的可复现配置。

在另一台电脑上 clone 后跑安装脚本，即可装回同一套 packages + 本地 `plan-mode` + agents。

## 当前包含什么

| 类型 | 内容 |
|------|------|
| **npm packages** | `pi-hashline-edit`, `pi-web-access`, `pi-codex-image-gen`, `@tintinweb/pi-subagents`, `pi-mcp-adapter`, `pi-skillful`（带版本钉） |
| **git packages** | `larryboiNEUQ/pi-auto-review`, `possibly/pi-gallery`, [`larryboiNEUQ/pi-inline-skill-complete`](https://github.com/larryboiNEUQ/pi-inline-skill-complete) |
| **本地 extension** | 官方 `plan-mode`（`/plan`, `Ctrl+Alt+P`） |
| **agents** | Explore / Plan / Worker / general-purpose |
| **可选模板** | permission 相关 config（`--with-templates`） |

### Skill 中间补全（新增）

Pi 0.81.x 原生 `/` 补全只在输入框最前自动弹出；正文中间要用：

| 插件 | 作用 |
|------|------|
| [`pi-inline-skill-complete`](https://github.com/larryboiNEUQ/pi-inline-skill-complete) | 正文中间输入 `$skill名` 自动补全，选中后插入 `/skill:name` |
| `pi-skillful` | 发送时把任意位置的 `/skill:name` 展开为完整 skill 内容 |

```text
请审查这段代码 $code-review
```

**不会**同步：`auth.json`、API keys、`models-store.json`、sessions、logs。

清单源文件：[`packages.json`](./packages.json)

## 新电脑快速安装

### 前提

```bash
npm install -g @earendil-works/pi-coding-agent
# 确认
pi --version   # 建议 >= 0.81
```

### 方式 A：clone 后安装（推荐）

```bash
git clone https://github.com/larryboiNEUQ/pi-dotfiles.git ~/.pi-dotfiles
cd ~/.pi-dotfiles
./scripts/install.sh
# 可选：同步主题/默认模型
./scripts/install.sh --with-settings
# 可选：权限扩展的 config 模板
./scripts/install.sh --with-templates
```

### 方式 B：一行

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash
```

带参数：

```bash
curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash -s -- --with-settings
```

### 装完后

```bash
pi list
# 新开一个 pi 会话
/login          # 各模型鉴权
/mcp setup      # 若用 pi-mcp-adapter
/plan           # 验证 plan-mode
/gallery        # 验证 pi-gallery（有图时）
# 正文中间输入 $skill名 验证 pi-inline-skill-complete
```

## 本机改完插件后如何回写仓库

在这台已经配好的机器上：

```bash
cd ~/.pi-dotfiles   # 或本仓库路径
./scripts/dump.sh --sync-locals
# 检查 packages.json 变更
git add -A && git commit -m "sync: update pi packages from machine" && git push
```

`dump.sh` 会：

1. 读 `~/.pi/agent/settings.json` 的 `packages`
2. 用 `~/.pi/agent/npm/package.json` 钉住已装 npm 版本
3. 写回 `packages.json`
4. `--sync-locals` 时把 `plan-mode` 与 `agents/*.md` 从本机拷回仓库

## 目录结构

```text
pi-dotfiles/
├── packages.json           # 唯一清单（远程包 + 本地资源声明）
├── settings.partial.json   # 可合并的非密钥偏好（主题/模型）
├── extensions/
│   └── plan-mode/          # 官方 plan-mode 拷贝
├── agents/                 # 子 agent 定义
├── templates/              # 可选 config 模板
└── scripts/
    ├── install.sh          # 安装入口
    ├── dump.sh             # 从本机导出
    └── quick-install.sh    # 新机一键
```

## 设计说明

1. **远程插件**走 `pi install <source>`，与官方包管理一致，写进 `~/.pi/agent/settings.json`。
2. **本地扩展**（官方 example 这类没有 npm 源的）拷进 `~/.pi/agent/extensions/`，Pi 启动自动加载。
3. **版本钉死**在 `packages.json`（如 `npm:pi-web-access@0.13.0`），减少换机时被漂到不兼容版本。
4. **密钥永不入库**；新机仍需 `/login` 与各自 API key 配置（如 `~/.pi/web-search.json`）。

## 安全

第三方 Pi package 拥有本机完整权限。`packages.json` 里每一项都应对应你信任的源。换机安装前可先：

```bash
./scripts/install.sh --dry-run
```

## License

MIT（其中 `extensions/plan-mode` 来自 `@earendil-works/pi-coding-agent` examples，遵循其原仓库许可。）
