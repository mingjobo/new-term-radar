# 我们的关键词研究平台

本 fork 用于个人、非商业的自动关键词研究。一期采用免费数据来源，使用现有 Neon 与 Vercel；上游的付费研究能力保留，后续按需要接入。

## 开发入口

- [一期统一架构](superpowers/specs/2026-10-21-new-term-radar-unified-architecture-design.md)
- [一期功能需求](superpowers/specs/2026-10-21-free-radar-sitemap-v1-requirements.md)
- [当前可执行计划](superpowers/plans/2026-10-21-unified-term-signal-v1.md)
- 自有仓库：<https://github.com/mingjobo/new-term-radar>
- 上游仓库：<https://github.com/zhuyansen/new-term-radar>
- 起始基线：`e2d33c335b7aface39e6c0eed29e61df5b5ff684`，上游版本 `0.4.0`。

## Git 约定

`origin` 指向 `mingjobo/new-term-radar`；`upstream` 指向 GitHub 确认的 fork parent `zhuyansen/new-term-radar`。`upstream/main` 是上游跟踪分支，`origin/main` 是我们集成并部署的平台分支。自己的开发使用 `codex/*` 分支，通过审查后合入 `main`。

本次开发分支为 `codex/free-keyword-platform`。不另建一条手工维护的“上游副本”分支；远端跟踪分支已经承担该用途。

后续同步上游的流程：

```bash
git fetch upstream
git fetch origin
git switch -c codex/sync-upstream-YYYYMMDD origin/main
git merge --no-edit upstream/main
uv run --no-project --with pytest --with markdown --with mcp python -m pytest -q tests
```

解决冲突并跑平台回归后，再通过 PR 合入 `main`。不用强制推送覆盖自有提交，不从本 fork 发布上游同名 PyPI 包或 MCP Registry 条目。平台上线时使用独立的 `free-platform.yml`；上游 `RADAR_ENABLED` 保持未设置。

## 当前进度

2026-10-15：

- 已克隆自有 fork，配置两个 remote，并创建本地开发分支。
- `origin/main...upstream/main` 的差异为 `0 / 0`。
- 在隔离依赖环境安装上游测试所需的 `pytest`、`markdown`、`mcp` 后运行基线：**95 passed**。
- 已评估旧 `keyword-detective` 项目，具体迁入和舍弃项见设计文档。
- 当时产品功能、Neon 新表、Vercel 新页面及自动调度尚未实现；该历史记录不能当作今天的验收证据。

2026-10-21：`radar/` 已成为唯一主包；免费 GitHub/HF 采集、竞品 Sitemap 基线/差分、Neon 最小权限、统一工作台都已在开发分支完成，并逐项记录在 [验收记录](verification/2026-10-21-unified-v1.md)。免费 Actions 工作流仍默认关闭，正式库和正式站点均未启用。Vercel 已有 `new-term-radar` 项目和 `codex/free-keyword-platform` 的历史预览，但新工作台是否已生成新预览以验收记录中的实际部署结果为准，不以本地代码完成代替上线。

## 旧项目边界

旧项目目录为 `/Users/evan/Desktop/Code/keyword-detective`。它没有可合并的 Git 历史，本次采用有记录的文件迁入和数据兼容，而非 Git merge。不要把 `.env`、浏览器用户目录、抓取产物或历史数据库文件放进这个公开仓库。旧目录保留，数据库旧表保留。
