# 同步入口梳理

2026-10-05 读取现有实现得出以下约束。审阅者实际模型为 `devin/claude-opus-5.5`，任务 `a6de2cc4-6d35-416`。本记录只描述改造前行为。

## Overview

安装从仓库写入本机，导出从本机写入仓库，quick-install 获取仓库后调用安装。尚无审计、基线、冲突识别或配置回滚。

## Key concepts

插件清单有固定和 latest 两套来源。参数位于独立的部分设置文件。安装与导出各自维护本地资源范围。

## How it works

安装器验证固定版本，先执行插件安装，再复制资源和可选参数。插件失败仍继续。导出重新固定 npm 版本，复制硬编码资源路径。quick-install 忽略 pull 失败，并可能删除已有目标目录。

## Where things live

- `scripts/install.sh` 拥有安装、资源复制与参数合并。
- `scripts/dump.sh` 拥有插件来源和部分资源导出。
- `scripts/quick-install.sh` 获取仓库后调用安装。
- `scripts/tests/test_package_profiles.py` 使用临时目录和假 Pi 测试命令入口。

## Gotchas

- dry-run 仍创建目录，需要改为完全只读。
- `pi install` 会写 package 注册。配置失败回滚不能抹去已完成升级的注册。
- 字段白名单必须集中。复制整个文件会带入未知字段，复制所有 agents 会带入外部拥有文件。
- 参数根目录与 HOME 不相同，测试和实现需同时处理。
- 缺失不代表删除，导出不能移除机器缺失项。
- 移除 MCP 清单不代表卸载本机。其当前入口应显式排除，避免永久待分类噪声。
- 旧 tests 对固定来源和设置可选行为的断言需按新规格迁移。
- 不能按日期重写 metadata，否则重复导出产生无意义 diff。

## 测试基线

测试基线尚待运行，不能把梳理代理未运行测试当作通过。
