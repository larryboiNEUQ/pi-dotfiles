# GitHub issue tracker

本仓库的规格和实施票位于 `larryboiNEUQ/pi-dotfiles` 的 GitHub Issues。所有操作使用 `gh`，显式传入 `--repo larryboiNEUQ/pi-dotfiles`。

## 操作约定

- 创建使用 `gh issue create --repo larryboiNEUQ/pi-dotfiles --title "..." --body-file "..."`。
- 读取使用 `gh issue view <number> --repo larryboiNEUQ/pi-dotfiles --comments`，同时查看标签和正文。
- 查询使用 `gh issue list --repo larryboiNEUQ/pi-dotfiles --state open --json number,title,body,labels,comments`，按任务和标签收窄范围。保留正文、标签名和评论正文，不只看标题。
- 评论使用 `gh issue comment <number> --repo larryboiNEUQ/pi-dotfiles --body-file "..."`。
- 标签使用 `gh issue edit <number> --repo larryboiNEUQ/pi-dotfiles --add-label "..."` 或 `--remove-label "..."`。
- 关闭使用 `gh issue close <number> --repo larryboiNEUQ/pi-dotfiles --comment "..."`。未验证完成的票保持打开，不关闭或修改源任务的 parent issue。

## 发布与依赖

技能要求发布规格或票时，创建 GitHub issue，不再只创建本地票。完整规格作为 parent，垂直实施票引用它。每张可由代理执行的票使用 `ready-for-agent` 标签。

按阻塞顺序创建票。GitHub 原生 issue dependencies 是阻塞关系的权威记录。先获取阻塞票的数据库 `id`，再使用以下请求。

```bash
	gh api repos/larryboiNEUQ/pi-dotfiles/issues/<child>/dependencies/blocked_by --method POST -F issue_id=<blocker-database-id>
```

原生依赖不可用时，在票的 `Blocked by` 中保留真实 issue 链接，并明确报告能力缺口。只有全部 blocker 完成才进入实施 frontier。

本地 `.scratch/` 是草稿和迁移索引，不是第二个 tracker。迁移后保留远端链接，避免下一次重复发布。

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding

地图 issue 使用 `wayfinder:map`。子票使用对应的 `wayfinder:<type>` 标签，并通过 sub-issue 关系连接地图。原生 sub-issue 不可用时，正文引用地图。仅在实际使用该流程时创建对应标签。

取票前枚举地图的 native sub-issues，再查询候选票的开放 blocker 和 assignees。排除仍有开放 blocker 或已被领取的票，按地图顺序选择第一张可执行票。原生关系不可用时，按地图任务列表和正文中的 `Blocked by` 链接判断。

需要领取时使用 `gh issue edit <number> --repo larryboiNEUQ/pi-dotfiles --add-assignee @me`。验证后先评论结果，再关闭实施票，最后在地图 Decisions-so-far 中追加结论与证据链接。保留源任务 parent 的其他内容，不关闭 parent；只有明确授权维护地图时才追加它的记录。

GitHub issue 与 PR 共用编号空间。含糊编号先用 `gh pr view` 辨别，非 PR 再读取 issue。
