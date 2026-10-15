# Free Keyword Research Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current session. If the user selects delegated execution, use superpowers:subagent-driven-development instead. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在自有 fork 上交付每天自动更新、可追溯证据、支持 3/14 天复查的免费个人关键词研究平台。

**Architecture:** 保留上游 `radar/`，在 `radar_platform/` 添加免费入口、Neon 状态和只读网页；从旧项目迁入 85 个词根及历史查询兼容层。Actions 领取持久任务并采集，Vercel 查询 Neon；新平台的运行成功不依赖上游付费模块。

**Tech Stack:** Python 3.12、标准库 WSGI/HTTP/HTML parser、psycopg 3、Neon Postgres、GitHub Actions、Vercel、HTML/CSS/原生 JS、pytest。

**Spec:** [2026-10-15-free-keyword-platform-design.md](../specs/2026-10-15-free-keyword-platform-design.md)。执行前完整阅读；本计划和该设计一起交付。

## Global Constraints

- 个人非商业使用；一期不配置或调用付费 API、付费模型，不自动升级服务套餐。
- 自有 `origin=mingjobo/new-term-radar`，`upstream=zhuyansen/new-term-radar`；自己的代码在 `codex/*`，上游更新经同步分支合入 `main`。
- 平台采用 Python 3.12；保持上游 Python 3.10/3.12 测试。新平台暂从源码 checkout 运行，保留上游包名和打包方式，不发布同名 PyPI/MCP 包。
- 沿用 Neon `keyword-detective` / `wandering-bonus-68047611`；开发先在 `dev-free-platform`，验收后迁移到现有 `production`。
- 数据库和任务使用带时区 UTC；日/周报告按 `Asia/Shanghai` 划分。
- 快任务每 8 小时：`17 0,8,16 * * *` UTC；日任务：`47 1 * * *` UTC；周一日任务生成周报。
- 每次 tick 最多 200 个 HTTP 请求、12 分钟；单来源任务最多 60 个请求、180 秒；请求超时 30 秒；租约 300 秒。所有重试计入预算。
- 429 尊重 `Retry-After`，缺失时推迟 1 小时；5xx/超时推迟 5、15、60 分钟，单周期最多 3 次重试（共 4 次尝试）；之后失败并等下周期。退避是最早可重试时刻，由下一次唤醒执行。
- sitemap 同站至少间隔 5 秒或更长的 crawl-delay；先查 robots；每站最多 20 个 sitemap 文档、20,000 个 URL、单个解压响应 5 MiB，快照压缩后 4 MiB。
- 只保留有证据的用途候选，不展示虚构搜索量/SEO 难度；单条摘录最多 500 字符；保留名称版本和实体身份。
- 保存 90 天观测和报告、30 天运行明细、48 小时 GitHub 原始计数；有引用的证据继续保留。700 MiB 预警、850 MiB 暂停新采集。
- 网页只接受显式只读连接；线上没有采集入口；旧目录、旧数据库表及上游 MIT 版权声明保留。
- 数据库集成测试只读 `RADAR_TEST_DATABASE_URL`，绝不回退到 `DATABASE_URL`，绝不自动加载旧项目 `.env`。

## Review Focus

1. 8 小时 GitHub 观测冒充 24 小时增量：Task 3 用跨周期计数测试约束时间窗。
2. 同名不同实体、HF demo/量化版本造成误合并或虚增来源：Task 1/3/6 测实体键、显式别名与来源类别计数。
3. 成功 HTTP 返回空内容/截断分页，导致基线被污染：Task 3/5 测失败保留状态，首次建基线不报全量新词。
4. 任务崩溃、重试及租约过期后旧 worker 迟到：Task 2/7 测事务、幂等、补做和拒绝过期提交。
5. 有数据但已过期、第三方文本带 HTML、旧 Trends 局部更新被隐藏：Task 4/8 测状态区分、转义、只读权限和逐词根更新时间。

## 文件地图与执行顺序

| 路径 | 责任 |
|---|---|
| `radar_platform/models.py`, `config.py`, `__main__.py` | 共用合同、配置、独立 CLI |
| `radar_platform/http.py` | 免费网络边界、请求预算、退避、响应上限 |
| `radar_platform/db.py`, `repository.py`, `migrations.py` | 连接、事务、迁移；运行时不建表 |
| `schema/platform/001_initial.sql`, `002_roles.sql` | 版本化平台表与最小角色权限 |
| `radar_platform/adapters/*.py` | GitHub/HF/sitemap/GSC 采集与纯结果 |
| `radar_platform/normalize.py`, `phrases.py`, `ranking.py` | 实体键、用途关系、解释排序 |
| `radar_platform/jobs.py`, `runner.py`, `checks.py`, `reports.py`, `retention.py` | 持久任务、复查、报告、保留策略 |
| `radar_platform/queries.py`, `web.py`, `auth.py`, `legacy_trends.py` | 只读查询和网页服务 |
| `radar_platform/templates/index.html`, `static/app.js`, `static/app.css` | 页面、交互、样式 |
| `api/index.py`, `vercel.json`, `.vercelignore` | Vercel 展示入口 |
| `config/platform.json`, `root-keywords.json`, `aliases.json`, `hf-task-map.json` | 可审查的非密钥配置 |
| `requirements-platform.in`, `requirements-platform.txt` | 运行依赖输入与锁定结果 |
| `tests/platform/`, `tests/platform_integration/`, `tests/e2e/` | 离线逻辑 / 隔离数据库 / 浏览器验收 |
| `.github/workflows/platform-ci.yml`, `free-platform.yml` | 测试和定时运行 |
| `scripts/platform_probe.py`, `scripts/review_candidates.py` | 有预算的在线验证、人工质量样本 |
| `docs/operations/platform.md`, `docs/verification/*.md` | 操作手册与实际验证证据 |

顺序：0 → 1 → 2 → 3 → 4（第一条闭环）→ 5 → 6 → 7 → 8 → 9。完成代码和部署验证后才进入真实 14 天观察；观察期间的问题回到对应任务修复。

## Task 0：fork 与测试基线（本次已完成）

- [x] 克隆到 `/Users/evan/Desktop/Code/new-term-radar`，核对 GitHub fork parent，配置 `origin`/`upstream`。
- [x] 从 `origin/main` 的 `e2d33c335b7aface39e6c0eed29e61df5b5ff684` 建立 `codex/free-keyword-platform`；默认推送远端为 `origin`。
- [x] 核对 `origin/main...upstream/main` 为 `0 / 0`，工作区没有既有产品改动。
- [x] `uv run --no-project --with pytest --with markdown --with mcp python -m pytest -q` → **95 passed**。
- [x] 记录旧项目取舍、Neon 标识和 Vercel 未登录前置。没有执行新的线上采集或写库。

## Task 1：独立免费入口、合同与归一化

**Files:** Create `radar_platform/{__init__,__main__,models,config,normalize,http}.py`, `config/{platform,root-keywords,aliases,hf-task-map}.json`, `tests/platform/{conftest,test_config,test_normalize,test_http}.py`。Modify `.gitignore`（加入 `.vercel/`、本地环境变体与验证产物目录）。

**Interfaces:** `load_config(path: Path) -> PlatformConfig`；`normalize_text(value: str) -> str`；`canonical_key(event: EvidenceInput, aliases: dict[str,str]) -> str`；`HttpClient.request(method: str, url: str, *, headers: dict|None=None, body: bytes|None=None) -> HttpResponse`。全部 dataclass 在 `models.py` 定义：

- `EvidenceInput(source_instance, external_id, entity_key, name, kind, language, url, excerpt, observed_at, data_window, metrics, content_hash, is_discovery, evidence_id=None)`；kind 为 `name|generic|unknown`，时间带时区，metrics/data_window 为 dict；采集时 evidence_id 为空，从库中读取时为已保存证据的 ID。
- `SourceSnapshot(version: int, payload: dict, last_success_at: datetime|None)`；`CollectionResult(status, observations: list[EvidenceInput], next_snapshot: dict|None, coverage: dict)`，status 为 `ok|baseline|off|incomplete`；网络异常由 runner 记录 failed。
- `Lease(job_key, lease_token, task, payload, scheduled_for)`；`RelationInput(name_key, generic_key, phrase, language, evidence_id, quote, rule_version)`。
- `PlatformConfig(sources, roots, aliases, hf_task_map, budgets, timezone)`；`HttpResponse(status, headers, body)`；`RunSummary(status, jobs, new_terms, requests, errors)`。配置不存密码。

- [x] **Step 1: 写失败测试。** 85 词根保持原顺序/无重复；C++ 与 C#、model 2.1 与 model 2.2 不合并；两个同名不同 repo 生成不同实体键；只有 aliases 显式配置才合并。
- [x] **Step 2: 测免费边界。** paid provider 配置及 AIsa/GoAnyAPI 请求必须拒绝；设置付费环境变量不增加 collector。第 201 个 tick 请求 / 第 61 个来源请求触发预算异常；私有地址和越界重定向被拒绝。
- [x] **Step 3: 运行** `python -m pytest -q tests/platform/test_config.py tests/platform/test_normalize.py tests/platform/test_http.py`，确认新模块缺失导致失败。
- [x] **Step 4: 实现。** 仅从旧 `app/config.py` 导出 ROOT_KEYWORDS 并记旧文件摘要；默认 GitHub/HF on、GSC off、sitemap 待探测；提供 `python -m radar_platform config-check --config config/platform.json`。
- [x] **Step 5: 重跑新测试和上游回归，预期全过。** config-check 只输出免费来源、预算和时区。
- [x] **Step 6: 提交** `feat: add isolated free platform contracts and config`。

## Task 2：隔离 Neon、迁移与原子入库

**Files:** Create `radar_platform/{db,repository,migrations}.py`, `schema/platform/{001_initial,002_roles}.sql`, `requirements-platform.in`, `requirements-platform.txt`, `tests/platform_integration/{conftest,test_migrations,test_repository}.py`, `docs/operations/platform.md`。Modify `requirements.txt`（增加 `-r requirements-platform.txt`，让 Vercel 实际安装 psycopg）。

**Interfaces:** `Repository(dsn: str, *, schema: str="public")`；`claim_due(now: datetime, *, limit: int=1, lease_seconds: int=300) -> list[Lease]`；`commit_source(lease: Lease, result: CollectionResult, *, expected_version: int, now: datetime) -> dict`；`enqueue(job_key: str, task: str, due_at: datetime, payload: dict) -> bool`；`finish_job(lease: Lease, result: dict, now: datetime) -> None`；`fail_job(lease: Lease, error: dict, retry_at: datetime|None, now: datetime) -> None`；`get_source_state(source_instance: str) -> SourceSnapshot`。

- [ ] **Step 1: 准备隔离环境。** 按 Neon branch 工作流在指定项目查找或建立 `dev-free-platform`，记录 branch ID/host；连接只存忽略的配置。建立 reader/writer/migrator 角色，复用现有项目。
- [ ] **Step 2: 写安全测试入口。** 显式 RADAR_TEST_DATABASE_URL 的 host 必须匹配 RADAR_TEST_ALLOWED_HOST；已知生产 endpoint `ep-silent-tooth-aq1rgb46` 及 pooler 变体必须拒绝。每次测试仅建立/清理自身 `radar_test_<uuid>` schema。
- [ ] **Step 3: 写失败用例。** `test_migrations_idempotent_and_checksums_match`、`test_repeat_slot_does_not_duplicate`、`test_next_slot_keeps_observation`、`test_failed_commit_keeps_previous_snapshot`、`test_two_workers_cannot_claim_same_job`、`test_expired_lease_cannot_commit`；词/证据/快照/成功记录全成或全不成。
- [ ] **Step 4: 运行** `python -m pytest -q tests/platform_integration/test_migrations.py tests/platform_integration/test_repository.py`。未配置隔离库明确 skip，不能计为关卡通过。
- [ ] **Step 5: 实现设计中的九张表、索引、约束和事务。** reader 仅 SELECT，writer 仅新表 DML；迁移单独直接连接。commit_source 同时完成来源job和run，拒绝过期lease；基线中未发现实体只存source_state。提供 `python -m radar_platform migrate --database-env RADAR_MIGRATION_DATABASE_URL`，checksum 不符失败，运行时不建表。按设计固定环境变量命名，使用 `uv pip compile requirements-platform.in --output-file requirements-platform.txt` 锁定依赖。
- [ ] **Step 6: 在隔离分支跑全测试。** reader INSERT 被数据库拒绝，旧 Trends 表结构/行数不变。记录真实结果。
- [ ] **Step 7: 提交** `feat: persist platform state and jobs in Neon`。

## Task 3：GitHub 与 Hugging Face 真实入库

**Files:** Create `radar_platform/adapters/{__init__,github,huggingface}.py`, `radar_platform/runner.py`, `scripts/platform_probe.py`, `tests/platform/{test_github,test_huggingface,test_runner}.py`, `tests/platform_integration/test_ingest.py`。

**Interfaces:** 每个 adapter 提供 `collect(cfg: PlatformConfig, previous: SourceSnapshot, now: datetime, http: HttpClient, *, source_instance: str) -> CollectionResult`；实例为 `github:breakout`、`hf:models`、`hf:spaces`，由 lease.payload 传入。`run_source(repo: Repository, lease: Lease, cfg: PlatformConfig, now: datetime, http: HttpClient) -> dict` 负责采集/事务/失败记录。

- [ ] **Step 1: 写 HF fixture 测试。** 首次只建 top100 基线；第二轮进入 top50 才生词；同周期重跑不增词；空列表或格式变化不覆盖基线；量化版本、model/demo 按规范实体及显式别名处理。
- [ ] **Step 2: 写 GitHub 测试。** 14 天/300 stars/200 平均每天或约 24h +400；8h +200 不等于日增。保留 48h 原始计数，找距当前 20–28h 最近观测，窗口不足不用 delta；保存 repo ID、URL、真实时间。
- [ ] **Step 3: 运行** `python -m pytest -q tests/platform/test_github.py tests/platform/test_huggingface.py tests/platform/test_runner.py`，确认失败。
- [ ] **Step 4: 实现适配器。** 复用上游纯算法，修正日增窗口；所有请求走 HttpClient。保留完整来源观测及其是否为新候选，供复查用；失败不更新 last_success。
- [ ] **Step 5: 跑离线/隔离库测试。** 注入采集成功但写库失败，重试仍产出相同词和证据；其他来源正常提交。
- [ ] **Step 6: 真实探测。** `python scripts/platform_probe.py --sources github,hf --max-requests 8 --out artifacts/probes/free-sources.json` 默认只验证结构；检查后用显式 `--write-test-db` 入隔离库。同次 HF 重跑只证明幂等，真实新词差分另待后续观测。
- [ ] **Step 7: 提交** `feat: ingest free GitHub and Hugging Face signals`。

## Task 4：最小只读网页

**Files:** Create `radar_platform/{queries,web,auth}.py`, `radar_platform/templates/index.html`, `radar_platform/static/{app.js,app.css}`, `api/index.py`, `vercel.json`, `.vercelignore`, `.python-version`（3.12）, `tests/platform/test_web.py`, `tests/platform_integration/test_readonly.py`。

**Interfaces:** `ReadQueries(dsn: str, *, schema: str="public")`；`overview(now: datetime) -> dict`；`terms(filters: dict, *, cursor: str|None=None, limit: int=50) -> dict` 返回 items/next_cursor；`term(term_id: str) -> dict|None`；`sources(now: datetime) -> list[dict]`；`create_app(queries: ReadQueries, *, username: str, password_sha256: str) -> Callable`。

- [ ] **Step 1: 写 WSGI 失败测试。** 无凭据全站 401；正确凭据 GET 成功；POST refresh/research 均 405；缺 RADAR_READ_DATABASE_URL 失败且不回退 writer；第三方 HTML 显示为文字，javascript URL 不生成链接。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_web.py`，确认失败。
- [ ] **Step 3: 实现 GET** `/api/overview`、`/api/terms`、`/api/terms/<id>`、`/api/sources` 与列表/详情页。参数化 SQL，排序白名单，limit 最大100，稳定时间+ID游标；显示实际采集时间和证据链接。
- [ ] **Step 4: 适配旧部署模式。** Python WSGI 入口指向新 web；资源拆文件；Basic Auth 恒定时间哈希比较，服务端环境变量为 RADAR_WEB_USERNAME / RADAR_WEB_PASSWORD_SHA256；部署排除本地环境和产物。
- [ ] **Step 5: 验证可见闭环。** `python -m radar_platform serve --host 127.0.0.1 --port 8000`；浏览器展示 Task 3 的隔离库数据，详情回链 GitHub/HF；reader 权限测试通过。记录页面值与数据库一致。
- [ ] **Step 6: 提交** `feat: add read-only keyword dashboard`。

**关卡 A：** 两类真实免费来源 → 隔离 Neon → 本地网页；幂等、事务和权限证据齐全才算完成。

## Task 5：sitemap 与可选 GSC

**Files:** Create `radar_platform/adapters/{sitemap,gsc}.py`, `tests/platform/{test_sitemap,test_gsc}.py`。Modify `config/platform.json`, `scripts/platform_probe.py`。

**Interfaces:** 沿用 `collect(...)` 合同；每个 sitemap 配置独立 source_instance，GSC 实例含属性标识。复用 `sitemaps.slug_text`、`terms.by_source/surges`、`gsc.fresh_queries`。

- [ ] **Step 1: 写 sitemap 失败测试。** 首次仅建基线；3 个共享词新增 URL 产生路径候选；shard 超时/20,000 URL 超限不提交部分基线；robots 禁止则跳过；gzip/XML 异常不记为“无新词”；语言路径处理兼容上游用例。
- [ ] **Step 2: 写 GSC 测试。** 未配置 off，token 失效 failed；rowLimit 触顶继续分页，预算耗尽 incomplete；保留 query/page/window/impressions；重复窗口不重复生词。
- [ ] **Step 3: 运行** `python -m pytest -q tests/platform/test_sitemap.py tests/platform/test_gsc.py`，确认失败。
- [ ] **Step 4: 实现。** 先 robots 后 sitemap，安全解析 XML/解压、限制重定向；标题只抓允许页面，每站最多5页/周期。GSC token_uri 固定 Google OAuth，token 来自环境，日志脱敏；3天近期/60天基线/1天延迟/至少5展示。
- [ ] **Step 5: 真实探测站点。** 从上游 example 的 glama / lobehub-mcp 核对 robots 和 shard 大小，最多启用2个完整可读取站点；超限选更窄现有 shard，仍不可用则记录原因并从 example 选替代。至少一个 sitemap 实测通过才勾选；GSC 无授权保持 off。
- [ ] **Step 6: 提交** `feat: add bounded sitemap and optional GSC sources`。

## Task 6：有证据的通用词、排序与报告

**Files:** Create `radar_platform/{phrases,ranking,reports}.py`, `scripts/review_candidates.py`, `tests/platform/{test_phrases,test_ranking,test_reports}.py`。Modify `config/hf-task-map.json`, `repository.py`, `adapters/github.py`（有预算的README补读）。

**Interfaces:** `extract_phrases(event: EvidenceInput, cfg: PlatformConfig) -> list[RelationInput]`（输入必须有 evidence_id）；`rank_terms(terms: list[dict], roots: list[str]) -> list[dict]`；`build_report(repo: Repository, *, kind: str, period_start: datetime, period_end: datetime, now: datetime) -> dict`；`render_markdown(report: dict) -> str`；Repository 新增 `pending_phrase_inputs(rule_version: str, limit: int=20) -> list[EvidenceInput]`、`save_relations(relations: list[RelationInput], now: datetime) -> int`、`mark_phrase_processed(evidence_id: str, rule_version: str) -> None`、`save_report(report: dict) -> None`。无提取结果也标记该规则已处理，避免每次重复计算。

- [ ] **Step 1: 写失败用例。** 原句 `An AI image editor for product photos` 提取 `AI image editor` 并保留原句；只有 image 根词不生成该短语；无用途证据仍保存名称；HF 标签映射标明 metadata，不能伪造引文；路径候选不得标已验证用途。
- [ ] **Step 2: 写排序/报告测试。** 同家族 HF model/demo 只算一个来源类别；排序附理由，无虚构置信分；日/周边界用北京时间；成功无新词与来源失败文案不同。
- [ ] **Step 3: 运行** `python -m pytest -q tests/platform/test_phrases.py tests/platform/test_ranking.py tests/platform/test_reports.py`，确认失败。
- [ ] **Step 4: 实现保守提取。** 每tick最多读5份README，响应最多10,000字符，选择最多500字符用途段落写为证据；只从已保存摘录提取固定用途名词的2–6词短语。规则 `literal-purpose-v1`，HF映射 `hf-task-v1`。每名称最多5候选，证据不足返回空；每条保存证据键和规则版本。报告覆盖前一完整北京时间自然日/周；今日首页用实时查询。
- [ ] **Step 5: 验证30份有出处文档。** `python scripts/review_candidates.py export --limit 30 --out artifacts/review/candidates.json`；记录无候选文档及覆盖率；人工核验有输出关系的正确率，低于80%关闭对应规则并重测，名称雷达继续运行。
- [ ] **Step 6: 提交** `feat: derive evidence-backed phrases and research reports`。

## Task 7：持久调度、3/14天复查与恢复

**Files:** Create `radar_platform/{jobs,checks,retention}.py`, `.github/workflows/free-platform.yml`, `tests/platform/{test_jobs,test_checks,test_retention,test_workflow_policy}.py`, `tests/platform_integration/test_job_recovery.py`。Modify `runner.py`, `__main__.py`, `repository.py`。

**Interfaces:** `seed_jobs(repo: Repository, cfg: PlatformConfig, now: datetime) -> int`；`tick(repo: Repository, cfg: PlatformConfig, now: datetime) -> RunSummary`；`evaluate_check(term: dict, observations: list[dict], coverage: dict, *, checkpoint_days: int, due_at: datetime, now: datetime) -> dict`；`prune(repo: Repository, now: datetime) -> dict`。CLI `python -m radar_platform tick --config config/platform.json --max-jobs 20`。

- [ ] **Step 1: 写时钟测试。** 首见后准确产生+3/+14天唯一任务；提前不运行；迟到2天补做并记录delay；同日/周报告一份；首次来源建基线不生成新词检查。
- [ ] **Step 2: 写恢复测试。** worker崩溃300秒后可重新领取；旧lease提交被拒；数据成功后报告失败仅重做报告；漏3周期只补最新真实采集并记skipped slots；每个到期检查保留。
- [ ] **Step 3: 写检查结论测试。** 到期前观测不能判定；失败/截断为insufficient_data；到期后完整观测未达条件为not_sustained；满足条件为sustained。断言结果不等同商业需求判断。
- [ ] **Step 4: 运行** `python -m pytest -q tests/platform/test_jobs.py tests/platform/test_checks.py tests/platform/test_retention.py tests/platform_integration/test_job_recovery.py`，确认失败。
- [ ] **Step 5: 实现。** 周期job key=任务名+scheduled slot，检查key=term ID+3/14；报告key=种类+北京时间period start。seed_jobs每次tick对照当前最新到期slot补缺：把更早未领取周期采集标superseded并计漏跑，不替换有效运行中的lease；检查任务不合并。补最近7个完整日/上一完整周的缺失报告；缺观测标缺失。新词复查任务由seed_jobs幂等扫描补齐，避免入库后崩溃漏建任务。没有到期后的观测先排来源更新，最多等24h后记数据不足。
- [ ] **Step 6: 建免费workflow。** 独立concurrency group、cancel-in-progress=false、15分钟超时、contents read；仅传writer/GITHUB/GSC凭据。FREE_RADAR_ENABLED=true才定时运行，人工触发先使用隔离环境。状态全部在Neon，cache不是事实来源。报告写Actions summary；DB故障或所有启用来源超过24h无成功时退出非零。
- [ ] **Step 7: 验证额度/保留。** 700MiB告警、850MiB停采不影响查询；只清理未引用过期记录；不改旧Trends表；HTTP次数与总时长上限实际阻止后续请求。
- [ ] **Step 8: 提交** `feat: schedule recoverable free research and follow-up checks`。

## Task 8：完整dashboard与旧Trends兼容

**Files:** Create `radar_platform/legacy_trends.py`, `tests/platform/test_legacy_trends.py`, `tests/e2e/{conftest,test_dashboard}.py`, `requirements-dev.in`, `requirements-dev.txt`（锁定 pytest、pytest-playwright、markdown、mcp）。Modify `queries.py`, `web.py`, templates/static, `tests/platform/test_web.py`。

**Interfaces:** `LegacyTrendsQueries(dsn: str)`；`latest_by_root(root: str) -> dict|None`；ReadQueries新增 `reports(kind: str, *, limit: int=20) -> list[dict]`、`checks(term_id: str) -> list[dict]`。GET `/api/reports`, `/api/legacy-trends?root=...`，详情带relations/evidence/checks。

- [ ] **Step 1: 写历史测试。** A今天成功、B昨天成功时各自展示对应时间；同根词前后快照才能比较；来源/地区/时间窗不同不可数值比较；旧表缺失返回not_connected，新雷达正常。
- [ ] **Step 2: 写浏览器用例。** 列表→筛选→详情→证据→来源状态→历史；空结果/失败/过期区分；刷新页面不产生采集请求；窄屏可读。
- [ ] **Step 3: 运行** `python -m pytest -q tests/platform/test_legacy_trends.py tests/platform/test_web.py`，确认新增用例失败。
- [ ] **Step 4: 完成页面。** 按前端设计技能细化层级；用途候选、出处、更新时间、复查结论同屏可达；来源指标保留单位；移除“抓取数据”。
- [ ] **Step 5: 跑浏览器端到端。** 安装锁定dev依赖并执行 `python -m playwright install chromium`；`python -m pytest -q tests/e2e`。conftest在本机启动WSGI、配置浏览器http_credentials，复用Task 2隔离库检查和fixture；截图到忽略的artifacts/。再核对一条真实数据从网页到数据库一致。
- [ ] **Step 6: 提交** `feat: finish research views and preserve legacy Trends history`。

## Task 9：CI、部署与14天验收

**Files:** Create `.github/workflows/platform-ci.yml`, `docs/verification/rollout.md`。Modify `.github/workflows/test.yml`（上游测试范围）、`.github/workflows/publish.yml`（上游身份限制）、`docs/operations/platform.md`, `docs/FORK.md`；保留本次基线文档并追加新验证证据。

**Interfaces:** 提供 `python -m radar_platform health --max-age-hours 24` 输出来源freshness/欠账，异常退出非零；CI与本地使用相同测试入口。部署环境变量以操作手册为唯一清单。

- [ ] **Step 1: 建CI。** 原test.yml保留Python 3.10/3.12矩阵，范围为 `tests/test_radar.py`；新platform-ci用Python 3.12和dev锁定依赖。PR跑离线平台测试；受信任分支/人工触发才使用隔离Neon secrets运行integration/e2e，先 `python -m playwright install --with-deps chromium`。无集成库明确“未验证”；不使用pull_request_target执行不可信代码读取secrets。
- [ ] **Step 2: 限制上游发布。** publish.yml每个发布job加 `github.repository == 'zhuyansen/new-term-radar'`；我们只部署网站。上游RADAR_ENABLED保持未设置。
- [ ] **Step 3: 跑完整验证。** `python -m pytest -q tests`；集成数据库用例无skip；浏览器通过；HTTP spy确认free tick不触发付费provider；来源失败时网页与日报正确显示。
- [ ] **Step 4: 核实Vercel目标。** 本机CLI当前未登录；执行时先恢复账户登录/连接，再列出项目，用旧页面与Neon配置定位并记录项目ID/域名。没有匹配时报告具体阻塞，不自动新建替代项目。
- [ ] **Step 5: 部署预览。** 显式关联现有Vercel项目，preview指向隔离Neon reader并配置访问保护；核对浏览器→API→数据库。构建包不得包含.env、浏览器profile、测试产物或writer密钥。
- [ ] **Step 6: 生产切换。** 备齐迁移SQL diff、旧表行数对比、预览URL、测试报告供审查；审查完成后迁移production、配置reader/writer、发布现有Vercel项目。免费workflow合入默认main后启用FREE_RADAR_ENABLED。首次运行只记录真实采集与基线。
- [ ] **Step 7: 验证恢复。** 同slot重跑无重复；单来源失败不影响其他来源；漏一次后下次补做。故障演练优先隔离环境，生产只检查实际重复执行和恢复记录。
- [ ] **Step 8: 真实运行14天。** 逐日记录运行，每周记录Actions/Neon用量、人工质量；第3/14天结论必须有现场证据；不足14天标“试运行中”。自动化只研究，不自动改代码/买API。
- [ ] **Step 9: 提交验收证据** `docs: record rollout evidence and free-tier operating results`。不可用来源、未配置GSC、关闭的用途规则逐项列明。

## 关卡、回滚与执行证据

| 关卡 | 必须交付 | 不通过时 |
|---|---|---|
| A：Task 1–4 | 两类来源→隔离库→网页；幂等/权限通过 | 留在开发环境修正 |
| B：Task 5–8 | 一个可用sitemap、用途样本、模拟时钟复查、状态页、历史兼容 | 能力标失败/关闭，不宣称全完成 |
| C：Task 9 Step 1–7 | 预览与生产端到端、调度、恢复、额度记录 | 关闭FREE_RADAR_ENABLED，回退上一网页版本，保留数据排查 |
| D：14天 | 来源成功率、质量、3/14天结论、用量报告 | 延长验证或缩小来源，不自动采购数据 |

迁移只新增表/索引/权限；默认不删旧表。回滚应用与workflow即可停新任务，未完成jobs保留。不要drop schema或重建生产库。

每个任务完成时更新checkbox、记录commit、命令和结果；在线检查写清时间、目标分支和数据来源。未运行/跳过/失败/通过分别记录。

## 自审与已知前置

- Spec覆盖：来源Task 3/5；免费边界Task 1/7/9；持久化Task 2；用途/报告Task 6；调度/复查/成本Task 7；页面/历史Task 4/8；现场验收Task 9。
- 旧项目择优迁入，旧浏览器抓取不进入一期；这是本次用户允许取舍后的明确决定。
- Vercel登录与项目身份仅阻塞部署；GSC授权仅影响可选GSC；本地开发和隔离验证可继续。
- 真实来源可用性、用途词质量和14天无人值守仍待验证；对应关卡必须提供证据。
- 产品开发步骤尚未勾选。本次要求的计划、仓库基线和旧代码评估已形成可审查文档。
