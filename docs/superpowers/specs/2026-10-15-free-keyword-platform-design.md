# 免费自动关键词研究平台：fork 开发设计

日期：2026-10-15。状态：执行计划的设计基准，尚未实现。

本设计落实用户的三项决定：个人非商业使用；先做免费可用版本；以 `mingjobo/new-term-radar` 为开发仓库，持续跟踪其 fork 上游。它替代旧项目中 2026-10-13 方案的“以 keyword-detective 为代码基座”决定。

## 目标与交付

每天自动发现 AI/软件领域的新名称，附来源证据，尽可能提取有原文依据的通用用途词候选。用户打开网页即可看结果、变化和来源是否正常。第 3 天、第 14 天复查免费信号；每周汇总质量、故障与额度。没有付费 API 或模型密钥也能运行。

一期的“机会”只表示值得进一步研究的线索。没有数据就不展示搜索量、SEO 难度、市场规模、领先 Google 的天数或伪造的模型置信分。

## 已核实的基础

| 项目 | 事实与选用方式 |
|---|---|
| 自有代码 | `mingjobo/new-term-radar`，默认分支 `main`，本地 `/Users/evan/Desktop/Code/new-term-radar` |
| 上游 | GitHub fork parent 为 `zhuyansen/new-term-radar`；本次两个 main 均为 `e2d33c335b7aface39e6c0eed29e61df5b5ff684` |
| 上游测试 | 隔离依赖环境中 95 项通过；网络调用主要由测试替身替代，不代表在线链路通过 |
| Neon | 沿用 `keyword-detective`，project ID `wandering-bonus-68047611`，production branch ID `br-delicate-breeze-aqgmgrxx`；本地旧项目地址与该项目 endpoint 一致 |
| Vercel | 旧代码已有 Python WSGI 部署入口；CLI 当前未登录，因此线上项目 ID、域名和权限配置仍须在部署阶段读取核实 |
| 当前自动化 | fork 有上游工作流，`RADAR_ENABLED` 未设置；没有我们的免费平台工作流或数据库表 |

## 旧项目哪些合，哪些不合

| 旧资产 | 决定 | 原因 / 迁入位置 |
|---|---|---|
| `app/config.py` 的 85 个词根 | 迁入 | 作为兴趣标签，保存为 `config/root-keywords.json`；不是已存在需求的证据，也不当过滤白名单 |
| Neon 的旧 Trends 数据 | 保留并只读兼容 | `radar_platform/legacy_trends.py` 查询每个词根自己的最近成功快照，不重新导入到新词表 |
| `app/deployment.py`、`api/index.py`、`vercel.json` | 适配迁入模式和必要代码 | 复用 Python WSGI 只读展示路径，新增入口指向 `radar_platform.web` |
| `app/repository.py`、`app/service.py` | 不整包迁入 | 强绑定 Trends 表、单批次快照和运行时建 schema；新平台需要证据、任务和时间序列 |
| `app/diffing.py` | 保留思路与测试案例 | 旧实现比较整批快照，缺失根词会误导；新平台按来源和实体比较，历史页按同根词快照比较 |
| `app/frontend_assets.py` | 重做页面结构，借鉴已有交互 | 当前以 Trends 根词为中心，且仍展示线上不可用的“抓取数据”按钮；新页面是研究收件箱 |
| Chrome/CDP、BitBrowser、付费 DataForSEO 抓取 | 一期不迁入 | 非云端自动主链路；旧目录保留，未来单独评估实验任务 |
| `.env`、浏览器 profile、抓取缓存、翻译缓存 | 不迁入仓库 | 无需这些文件即可运行新平台；历史翻译可直接从旧表读取 |

代码上的主干是 fork。旧目录不删除。保留上游 MIT 授权、原作者和原有 CLI；自有平台放在 `radar_platform/`，少量修改原模块时配兼容测试。

## 架构和模块边界

```text
GitHub Actions 定时唤醒
  → radar_platform tick（免费来源白名单、任务领取、请求预算）
  → GitHub / HF Models / HF Spaces / sitemap / 可选 GSC
  → 完整采集结果 + 有来源的词条 + 用途词候选
  → Neon：词、证据、关联、来源快照、任务、执行记录、复查、报告
  → Vercel Python 只读接口
  → 今日概览 / 词条详情 / 运行状态 / 历史 Trends
```

新入口为 `python -m radar_platform`，不调用上游 `daily` 再拼一长串 `--skip`。上游新增付费模块不会自动进入我们的任务。新入口只登记免费适配器，并通过统一 HTTP 客户端控制域名、次数、超时和失败处理。上游 AIsa、GoAnyAPI、X、Reddit asks、revenue、judge、paid review、usecases 和 pains 不进入一期任务。

直接复用或包装上游的纯计算：`breakout.score/repo_term/variants`、`sources.base_name/_entered`、`sitemaps.slug_text`、`terms.by_source/surges`、`gsc.fresh_queries`。上游采集器的本地文件快照和 SQLite 不作为云端持久状态；适配器读取 Neon 状态并产出下一份快照，来源成功入库时再提交快照。依赖私有 helper 的适配器需有形状兼容测试。

平台采用 Python 3.12；保持上游 Python 3.10/3.12 测试。新增运行依赖仅 `psycopg[binary]`，前端先用 HTML/CSS/原生 JS，新增依赖精确锁定后提交锁文件。不引入付费模型、本地大模型、额外数据库或常驻服务器。

## 固定运行规则

- 时区：数据库和任务使用带时区 UTC；日/周报告按 `Asia/Shanghai` 划分。
- 快任务：GitHub、HF Models、HF Spaces 每 8 小时；唤醒 cron 为 `17 0,8,16 * * *` UTC，对应北京时间 08:17、16:17、00:17。
- 日任务：sitemap、已配置 GSC、用途提取、到期复查、日报；`47 1 * * *` UTC，对应北京时间 09:47。日报覆盖前一个完整北京时间自然日；首页“今日”直接查询当天实时入库结果。
- 周报：每周一的日任务内生成前一完整周的报告。恢复时最多补最近 7 个完整日和上一完整周的缺失报告，只用已有观测；无观测区间明确标缺失。所有唤醒都先处理持久队列中到期的任务，定时事件不是执行成功证据。
- 漏跑：保留未完成任务；周期采集恢复后只补一次最新真实采集，记录错过周期数，不捏造过去时点的数据。第 3/14 天检查逐条补做并标注延迟。
- 同一任务至少可能执行一次；唯一任务键、租约和事务保证重试不会重复生词、丢证据、重复报告。不宣称外部请求 exactly-once。
- 每次 tick 最多 200 个 HTTP 请求、12 分钟；单来源任务最多 60 个请求、180 秒；请求超时 30 秒；租约 300 秒。所有重试计入预算。
- 429 尊重 `Retry-After`，缺失时推迟 1 小时；5xx/超时推迟 5、15、60 分钟，单周期最多 3 次重试（共 4 次尝试）；之后失败并等下周期。退避时间是最早可重试时刻，实际重试由下一次唤醒执行。单来源失败不阻塞其他来源和状态页。
- sitemap 同站至少间隔 5 秒或更长的 crawl-delay；先查 robots；每站最多 20 个 sitemap 文档、20,000 个 URL、单个解压响应 5 MiB，快照压缩后 4 MiB。超限或分页不全标记 `incomplete`，保留旧基线，不做假差分。
- GitHub 维持上游初始阈值：14 天窗口、至少 300 stars、平均每天 200 stars 或最近约 24 小时新增 400 stars；8 小时间隔不得直接拿“上次 delta”冒充日增速。保留至少 48 小时计数观测，窗口不足时只用平均增速。
- HF 的 models/spaces 分开维护 top 100 基线，只将新进入 top 50 的实体作为新发现；首次仅建基线。
- GSC 未配置显示 `off`。配置后按上游 3 天近期 / 60 天基线 / 1 天延迟 / 至少 5 展示运行；补充分页，超过预算时标记不完整。

## 词、证据与用途的约束

名称的实体键来自 GitHub repo、HF 类型及 ID、sitemap URL。只通过明确的别名配置把跨来源实体认定为同一对象；相同拼写不自动证明同一个产品。通用词按语言与规范化短语去重。规范化使用 NFKC、大小写和空白整理，保留版本、小数点、C++/C# 等有含义符号。

每个证据保存来源实例、原始 ID、URL、实际采集时间、内容摘要、数据时间窗、指标和内容哈希。单条摘录最多 500 字符。相同来源/原始 ID/周期/词条唯一；重跑同周期不加一条历史，但下周期的新观测保留。未触发新发现的基线实体只进入来源快照；只有新发现或已经存在的词条才写入 terms/evidence，避免把首次 HF 全量当新词。

免费用途提取先限定为原文中明确存在的 2–6 词用途短语（如 `AI image editor`），或版本化的 HF 任务标签映射；每个关联带原句或标签值、证据 ID、提取规则版本。GitHub README 每次 tick 最多补读 5 份，响应最多 10,000 字符，选择最多 500 字符的首个用途段落作为可存储证据；提取只依据这段摘录。sitemap URL 中拆出的词只标为路径候选；没有页面/描述支持时不包装为产品用途。GSC 的真实查询标明站点和时间窗，不能推广为全网搜索量。

85 个词根用于标签与兴趣排序，不能独自生成用途关联。版本化别名和 HF 标签映射在配置中可审查。排序按来源类别数、来源内活动等级、词根关联、最近成功观测时间构成可解释顺序，不把 stars、排名、展示量直接相加。HF 模型及其 demo 算同一来源类别。

首次发现立即展示。第 3/14 天检查只有三类结论：`sustained`（所观察免费信号仍满足该来源条件）、`not_sustained`（完整观测中未继续满足）、`insufficient_data`（失败、缺失或不完整）。GitHub 看增速条件、HF 看 top 50、sitemap 看是否有新的相关 URL、GSC 看新的完整窗口内是否还有展示。它们不等价于有/无商业需求。检查使用到期后取得的完整观测，不能用到期前的旧数据冒充新验证。

## Neon 持久化与权限

仍使用既有项目，在普通隔离分支 `dev-free-platform` 上验证迁移与历史兼容；验收后把版本化 SQL 迁移应用到 `production`。两条分支连接信息放在环境配置，不能提交。所有新表使用 `radar_` 前缀：

| 表 | 责任 / 主要唯一约束 |
|---|---|
| `radar_schema_migrations` | 迁移版本与 checksum |
| `radar_terms` | 规范实体和类型；`canonical_key` 唯一 |
| `radar_evidence` | 来源观测与可引用摘录；`(source_instance, external_id, slot, term_id)` 唯一 |
| `radar_relations` | 名称 → 用途候选；`(name_id, generic_id, evidence_id, rule_version)` 唯一 |
| `radar_source_state` | 最近完整快照、版本与最后成功时间；来源实例唯一 |
| `radar_jobs` | 所有到期任务、租约、重试与任务结果；`job_key` 唯一 |
| `radar_runs` | 每次尝试的成功/失败/跳过/不完整、用量和耗时 |
| `radar_checks` | 检查结论、依据与实际时间；`(term_id, checkpoint_days)` 唯一 |
| `radar_reports` | 日/周报告数据；`(kind, period_start)` 唯一 |

单来源的词、证据、状态版本和成功记录一起事务提交；空/异常/不完整响应不能推进基线。任务领取用 `FOR UPDATE SKIP LOCKED` 与租约；提交校验租约所有者和状态版本，过期 worker 的迟到结果不得覆盖新结果。

Actions 使用仅限平台新表的写入角色；网页使用显式 `RADAR_READ_DATABASE_URL` 只读角色，不回退到 writer。schema 迁移使用单独直接连接，网页运行时没有建表或改 schema 的代码。旧 Trends 表只给查询权限。

固定环境变量：`RADAR_WRITE_DATABASE_URL`（任务写入）、`RADAR_READ_DATABASE_URL`（网页只读）、`RADAR_MIGRATION_DATABASE_URL`（迁移直连）、`RADAR_TEST_DATABASE_URL`/`RADAR_TEST_ALLOWED_HOST`（隔离测试）、`RADAR_WEB_USERNAME`/`RADAR_WEB_PASSWORD_SHA256`（网页访问）、可选 `GITHUB_TOKEN`/`GSC_TOKEN_JSON`。任何连接串和凭据不进入 Git。生产和预览使用各自环境中的同名变量。

保存 90 天观测和报告、30 天运行明细、48 小时 GitHub 原始计数。被用途关联/复查引用的证据继续保留；清理只删未引用的过期观测。达到 700 MiB 预警并停止增加完整原文/大快照，达到 850 MiB 暂停新采集并保留已有结果查询；不自动升级付费或删除旧项目数据。

## 网页交付

一个轻量 dashboard，加词条详情和历史 Trends：

1. 今日概览：新增名称、用途候选、待复查、最近执行时间；失败来源提示清楚。
2. 词条列表与详情：筛选来源/类型/日期/兴趣词根；原始链接、摘录、关联词、变化时间线、3/14 天结论。
3. 来源运行状态：未配置、未运行、基线建立、成功但无新词、不完整、失败、过期分别显示。
4. 日/周报告：保存为 Neon 中同一份结构化结果，网页与 Actions summary 共用内容。
5. 历史 Trends：旧数据只读，按根词展示自己的更新时间、来源和时间窗；旧表不存在时显示未接入。

线上无“抓取数据”“逐词研究”入口；“刷新页面”只重新读取已保存结果。HTML 逃逸来源内容；只允许 HTTP(S) 证据链接。只读服务独立测试：POST 返回 405，数据库角色不能写。内部网页采用 HTTPS 下的单用户 Basic Auth（用户名与密码哈希配置在服务端），全部页面和 API 都校验；不增加多租户账号体系。

## 交付与验收关卡

先完成 GitHub/HF → 隔离 Neon → 本地只读页面的真实闭环，然后补 sitemap/GSC、用途词、调度和报告，最后部署到现有 Vercel 并进行 14 天自动运行。

上线前必须有：上游回归、免费调用边界测试、数据库事务/并发测试、无数据库真实写入的单测、浏览器端到端、真实来源探测、一次真实任务重跑无重复。第 3/14 天逻辑先用可控时钟测试；14 天现场验证单独报告，未经过时间不勾选完成。

用途提取质量使用 30 份有来源的文档，记录提出了多少候选和人工核验的正确率；没有候选也计入覆盖率。若有输出的关联中正确率低于 80%，保持该规则关闭，仅展示原文用途摘录，修正规则后重测。

14 天报告至少包含：应运行/实际运行次数、每来源成功率和延迟、故障恢复、发现与去重数、用途候选覆盖率/人工有用率、3/14 天复查情况、Neon/Actions 使用量。任何未配置或未验证的能力明确列出。
