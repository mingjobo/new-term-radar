# Unified new-term-radar V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 `new-term-radar` 的 `radar/` 为唯一主程序，交付免费自动新词发现、竞品 Sitemap 增减和统一工作台。

**Architecture:** 先将已验证的 `radar_platform/` 功能迁入 `radar/platform/`，统一 CLI、打包和 Vercel 入口，原 `radar/` 发现规则继续作为领域核心。Neon 是自动任务唯一状态库，竞品 URL 事件与词条证据分存；现有 `keyword-detective` Trends 数据和自动采集都留到第二版，不进入 V1 页面或定时任务。

**Tech Stack:** Python 3.12、psycopg 3、Neon Postgres、GitHub Actions、Vercel WSGI、原生 HTML/CSS/JS、pytest、Playwright。

**Spec:** [统一架构设计](../specs/2026-10-21-new-term-radar-unified-architecture-design.md) 和 [V1 功能需求](../specs/2026-10-21-free-radar-sitemap-v1-requirements.md)。执行者先完整阅读两份；架构冲突处以统一架构设计为准，页面/行为验收以 V1 功能需求为准。

## Global Constraints

- 唯一运行仓库为 `mingjobo/new-term-radar`；`radar/` 是唯一主包。迁移完成后不保留被调度的 `radar_platform` 入口；保留原 `daily/sources/keywords/leads/pains/mcp` 命令兼容上游。
- 平台任务与部署使用 Python 3.12；原项目宣称的 Python 3.10+ CLI 兼容测试继续保留，不因合包无意提高旧命令版本门槛。
- V1 不运行、不查询、不展示 Google Trends；旧 Neon Trends 表与本地旧项目目录原样保留。`config/root-keywords.json` 的旧词根不是新词或搜索量证据。
- 免费 GitHub/HF 每 8 小时，Sitemap 每日；上游 `.github/workflows/radar.yml` 继续关闭，不调用 AIsa、GoAnyAPI、DataForSEO、TrustMRR 或付费模型。
- 只复用现有 `keyword-detective` Neon 项目：先在 `dev-free-platform` 分支和 Vercel 预览验收，不改生产。迁移使用直接连接与显式命令，运行时不建表。
- Sitemap 首次完整读取只建立基线；每站最多 20 个 Sitemap 文档、20,000 个 URL。空集、部分分片、格式异常、超预算均保留旧基线且不发增减事件。
- 数据库时间存带时区值；总览的五项指标、今日新词和竞品默认范围按 `Asia/Shanghai` 自然日；成功零变化与未采集分开。
- 看板使用 `RADAR_READ_DATABASE_URL`；设置写入只用新 `RADAR_SITE_ADMIN_DATABASE_URL` 且只可改站点配置；采集用 `RADAR_WRITE_DATABASE_URL`，迁移用直接的 `RADAR_MIGRATION_DATABASE_URL`。浏览器和 Vercel 不持有采集者凭据。
- HTTP(S) 公网地址保存时校验，连接及每次重定向时再次校验且固定已验公网 IP；设置写入防 CSRF；外部文字按文本渲染，外链只允许 HTTP(S)。
- 集成测试只使用 `RADAR_TEST_DATABASE_URL` 和匹配的 `RADAR_TEST_ALLOWED_HOST`，不能回退生产 URL；skip 不算通过。生产迁移/启用单独审批。

## Review Focus

1. **源码与已安装包名称不同。** 从源码 `radar.platform`、wheel 安装后的 `new_term_radar.platform` 及 Vercel 导入均成功；不能留下绝对导入 `radar_platform` 或让新子包漏打包（Task 1 `test_all_three_entrypoints_after_merge`）。
2. **两个采集入口意外双跑或调用付费服务。** 新 cron 只用主程序免费 `collect`，旧 workflow 默认 off，同周期 job key 幂等（Task 10 `test_only_free_collect_is_scheduled`）。
3. **DNS 重绑定、跨域重定向或私网地址。** 表单验证后实际连接仍须固定已校验公网 IP、TLS 校验原 host（Task 4 `test_public_ip_pinned_across_redirects`）。
4. **Sitemap 分片失败/空集造成假移出。** 旧 URL 集、版本和事件数均保持不变，其他站继续执行（Task 5 `test_incomplete_site_keeps_previous_snapshot`）。
5. **跨北京时间零点及大量列表。** 五指标共用所选日半开区间；20 站/单站 1,000 事件仍由 SQL 筛选和分页，未采集不显示 0（Task 7 `test_overview_day_boundary_and_missing_state`，Task 8 `test_large_competitor_pages_match_counts`）。

---

## File map and contracts

| 文件 | 职责 |
|---|---|
| `radar/__main__.py`, `radar/platform/commands.py`, `pyproject.toml`, `api/index.py` | 单一 CLI、打包和网站入口；保留上游命令 |
| `radar/{breakout,sources,sitemaps,sitemap_urls}.py` | 可复用发现规则、Sitemap 安全 URL 核心与旧命令兼容 |
| `radar/platform/{models,config,normalize,http,db,migrations,repository,queries,runner,web,auth}.py` | 将当前 `radar_platform` 设施搬入主包，随后扩展，不双写 |
| `radar/platform/adapters/{github,huggingface,sitemap}.py` | 免费来源的 HTTP/证据适配；领域规则引用 `radar/` |
| `radar/platform/{schedule,site_store,site_admin}.py` | 周期任务、竞品原子基线/事件、设置限权写入 |
| `schema/platform/004_sitemap.sql`, `005_site_roles.sql` | 竞品数据表、索引与显式角色权限；001～003 checksum 不改 |
| `radar/platform/templates/index.html`, `radar/platform/static/{app.js,app.css}` | 同一个 Term Signal 网站的侧栏、看板、设置与研究卡 |
| `.github/workflows/free-platform.yml`, `docs/operations/platform.md` | 免费 cron 与预览/启用/回退操作 |
| `tests/test_radar.py`, `tests/platform/`, `tests/platform_integration/`, `tests/e2e/` | 原项目兼容、离线、隔离 Neon、浏览器验收 |

接口约定：平台包中的内部导入全部相对引用，领域规则用 `from ..`/`from ...`，让源码包和安装包都可用。新 CLI 为 `python -m radar collect --kind sources|sites`，已安装命令同参数；`migrate`、`serve` 和 `config-check` 也归入该主 CLI。`SiteStore.commit_complete(site_id: UUID, run_key: str, scheduled_for: datetime, urls: set[str], observed_at: datetime) -> dict[str,int]` 是唯一推进竞品 URL 基线的事务入口；`run_key=site:<uuid>:<UTC slot>`，旧 slot 不得覆盖新基线。

### Task 1: 合并 Python 包和入口，不改产品行为

**Files:** Move `radar_platform/**` → `radar/platform/**`（源代码、模板和静态文件）；Modify `radar/__main__.py`, `api/index.py`, `pyproject.toml`, `tests/platform/**`, `tests/platform_integration/**`, `tests/platform/test_deployment.py`, `docs/operations/platform.md`；Create `radar/platform/commands.py`, `tests/platform/test_package_merge.py`。

**Interfaces:** `radar.platform.web.create_app_from_env(environ: Mapping[str,str] | None = None) -> Callable`；`radar.platform.commands.run_platform_command(command: str, argv: list[str]) -> int` 处理 `migrate/serve/config-check`，由 `radar.__main__.main` 在读取旧 `config.json` 前分派；原 `daily/sources/keywords/leads/pains/mcp` 入参及返回不变。

- [ ] **Step 1: 写失败测试。** `test_all_three_entrypoints_after_merge` 验证源码 `radar.platform`、安装 wheel 的 `new_term_radar.platform`、Vercel `api.index` 导入；`test_legacy_cli_commands_still_parse` 验证旧命令；`test_no_live_radar_platform_imports` 搜索运行代码和测试引用；现有网页/入库测试保持原断言。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_package_merge.py tests/platform/test_deployment.py tests/test_radar.py`，确认新增测试因尚未合包失败。
- [ ] **Step 3: 搬移文件并修导入。** 让 `radar/__main__.py` 在加载旧 `config.json` 前分派 `config-check/migrate/serve`；`pyproject.toml` 显式包含子包和包内模板/静态文件，`api/index.py` 只指向主包；更新操作命令，移除旧顶层包，不保留双运行入口。
- [ ] **Step 4: 运行** `python -m pytest -q tests/test_radar.py tests/platform tests/platform_integration`；集成环境未配置则单独标未验证，不能写“全通过”。构建 wheel 并在隔离目标目录导入 `new_term_radar.platform.web`；检查 Vercel 页面、`/api/terms` 的现有行为与迁移前相同。
- [ ] **Step 5: 提交** `refactor: fold free platform into radar package`。

### Task 2: 收敛 GitHub/HF 规则并验证第二次采集

**Files:** Modify `radar/{__main__,breakout,sources}.py`, `radar/platform/adapters/{github,huggingface}.py`, `radar/platform/{runner,commands}.py`; Create `radar/platform/schedule.py`, `tests/platform/test_schedule.py`; Modify `tests/platform/{test_github,test_huggingface,test_runner}.py`, `tests/test_radar.py`。

**Interfaces:** `radar.breakout.qualifies(stars: int, age_days: float, delta_24h: int | None, velocity_min: int, delta_min: int) -> bool` 供旧 `score` 与免费适配器共用；`seed_source_jobs(repo: Repository, now: datetime) -> int`；`run_due_sources(repo: Repository, cfg: PlatformConfig, now: datetime, http_factory: Callable[[str], HttpClient], *, max_jobs: int) -> RunSummary`。

- [ ] **Step 1: 写失败测试。** `test_github_threshold_is_shared_by_legacy_and_free`；`test_hf_models_and_spaces_still_use_shared_base_name`；`test_three_source_jobs_once_per_eight_hour_slot`；`test_second_run_does_not_duplicate_term_or_slot_evidence`；`test_one_source_failure_does_not_block_others`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_schedule.py tests/platform/test_github.py tests/platform/test_huggingface.py tests/test_radar.py`，确认新增用例失败。
- [ ] **Step 3: 实现三个接口。** `collect --kind sources` 通过主 CLI 调 `run_due_sources`，只读取 `RADAR_WRITE_DATABASE_URL`；GitHub 24h delta 不用 8h 两次之差冒充，HF Models/Spaces 独立基线；同槽重复不增加证据。发现规则留在 `radar/`，适配层只负责请求和持久证据映射。
- [ ] **Step 4: 运行上述测试及** `python -m pytest -q tests/platform_integration/test_ingest.py`，无 skip；在 dev Neon 执行第二次真实 GitHub/HF 采集，核对三来源运行时间、基线与词条去重，记录至 `docs/verification/2026-10-21-unified-v1.md`。
- [ ] **Step 5: 提交** `feat: collect free sources through radar`。

### Task 3: 竞品配置、URL 状态和最小数据库角色

**Files:** Create `schema/platform/{004_sitemap,005_site_roles}.sql`, `radar/platform/{site_store,site_admin}.py`, `tests/platform_integration/test_sites.py`; Modify `tests/platform_integration/test_migrations.py`, `docs/operations/platform.md`。

**Interfaces:** `SiteAdmin.add_site(name: str, homepage_url: str, sitemap_url: str | None) -> UUID`；`SiteAdmin.update_site(site_id: UUID, *, name: str, sitemap_url: str | None, enabled: bool) -> None`；`SiteStore.list_enabled_sites() -> list[dict]`；`SiteStore.commit_complete(site_id: UUID, run_key: str, scheduled_for: datetime, urls: set[str], observed_at: datetime) -> dict[str,int]`。主页 host 不可编辑，换域名只能暂停旧站、增加新站。

- [ ] **Step 1: 写失败集成测试。** `test_first_snapshot_has_zero_events`、`test_three_added_two_removed_then_identical_run_zero`、`test_old_slot_cannot_revert_snapshot`、`test_reappearing_url_is_new_added`、`test_site_admin_role_cannot_change_terms_or_events`；20,000 URL 上限不进数据库。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform_integration/test_sites.py`，确认新用例失败。
- [ ] **Step 3: 实现两份增量迁移和两个存储类。** `radar_sites` 存 ID/名称/主页/固定 host/Sitemap/enabled；`radar_site_state` 存版本、URL 数、最近成功、最近 run key/slot；`radar_site_urls` 以 `(site_id,url)` 唯一；`radar_site_events` 以 `(site_id,run_key,event_type,url)` 唯一，类型只为 `added|removed`。`SiteAdmin` 在写入前校验公网 HTTP(S) 与同站 Sitemap；`commit_complete` 用站点行锁和单事务完成差分、事件、基线；旧 slot 拒绝，同 key 不重复。reader 只读所需表，writer 操作平台表，site-admin 仅 SELECT/INSERT/UPDATE `radar_sites`，不授予 DELETE 或默认全表权限。
- [ ] **Step 4: 在隔离 schema 运行** `python -m pytest -q tests/platform_integration/test_migrations.py tests/platform_integration/test_sites.py`，确认无 skip；在 dev Neon 建最小权限 SQL 登录角色并轮换密码，用 migrator 直连应用 004/005，第二次迁移 applied=[]，旧 Trends 表行数不变。
- [ ] **Step 5: 提交** `feat: store site snapshots and restrict settings role`。

### Task 4: 从原 Sitemap 模块抽出安全的 URL 核心

**Files:** Create `radar/sitemap_urls.py`, `radar/platform/adapters/sitemap.py`, `tests/platform/test_sitemap.py`; Modify `radar/{sitemaps}.py`, `radar/platform/http.py`, `tests/platform/test_http.py`, `tests/test_radar.py`。

**Interfaces:** `SitemapResult(status: Literal['complete','incomplete'], urls: set[str], documents: int, error: str | None)`；`discover_and_collect(site: Mapping[str,Any], http: HttpClient) -> SitemapResult`；`radar.sitemap_urls.normalize_url(url: str) -> str`。新监测不调用旧 `surges`、`slug_text` 或本地 `snap.save`。

- [ ] **Step 1: 写失败测试。** 普通 Sitemap、索引和必需分片、robots 声明、gzip、URL 大小写/默认端口/片段保守规范化；`test_public_ip_pinned_across_redirects` 验证私网/云元数据/跨域目标及 DNS 重绑定被拒；`test_empty_bad_xml_or_21_documents_is_incomplete`；`test_robots_disallow_and_crawl_delay`；原 `radar.sitemaps.diff` 的已有行为仍可通过离线测试。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_sitemap.py tests/platform/test_http.py tests/test_radar.py`，确认新增用例失败。
- [ ] **Step 3: 实现纯 URL 解析与免费适配器。** 同源 HTTP(S) 及每跳公网 IP 校验，连接绑定已验证 IP 且 TLS 以原 host 校验证书；沿用请求、响应、时长预算。XML 只抽 `<loc>`，20 文档、20,000 URL、解压后每响应 5 MiB；失败返回 incomplete。原模块只共享可靠的解析/规范化函数，不改变旧 CLI 的词暴涨输出。
- [ ] **Step 4: 运行上述测试**；对 `aiphotoeditor.com` 做只读探测，得到非空完整 URL 集，不写事件；失败时明确原因而非把空集当成功。
- [ ] **Step 5: 提交** `feat: share safe sitemap URL core`。

### Task 5: 每日站点任务、真实基线和故障保护

**Files:** Modify `radar/platform/{schedule,runner,commands,site_store}.py`; Create `tests/platform/test_site_runner.py`, `tests/platform_integration/test_site_ingest.py`。

**Interfaces:** `seed_site_jobs(repo: Repository, sites: SiteStore, now: datetime) -> int`；`run_due_sites(repo: Repository, sites: SiteStore, now: datetime, http_factory: Callable[[str], HttpClient], *, max_jobs: int) -> RunSummary`；主 CLI `collect --kind sites`。

- [ ] **Step 1: 写失败测试。** `test_first_complete_run_only_builds_baseline`、`test_three_additions_two_removals_then_no_changes`、`test_incomplete_site_keeps_previous_snapshot`（缺片/空集/预算）、`test_site_failure_does_not_block_other_site`、`test_pause_keeps_history_and_prevents_jobs`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_site_runner.py tests/platform_integration/test_site_ingest.py`，确认新增用例失败。
- [ ] **Step 3: 实现每日 seed/执行。** 站点从 Neon 配置读取，保存设置不立即抓取；成功时调用 Task 3 原子提交并用现有 `Repository.finish_job` 记录尝试，失败/不完整仅记录尝试、不动旧基线；同 run key 重试不重复写事件，错过时段不伪造历史。
- [ ] **Step 4: 运行上述测试且无 skip**；在 dev Neon 为 `aiphotoeditor.com` 建首次真实完整基线，记录实际 URL 数和零事件；同周期重跑事件仍为零。日期差分只用受控测试验证，不制造外网站点的假变化。
- [ ] **Step 5: 提交** `feat: run daily sitemap comparison`。

### Task 6: 设置的唯一写入接口

**Files:** Modify `radar/platform/{web,auth}.py`, `tests/platform/test_web.py`; Create `tests/platform/test_site_admin_web.py`, `tests/platform_integration/test_site_admin_permissions.py`。

**Interfaces:** `create_app(queries: ReadQueries, *, username: str, password_sha256: str, site_admin: SiteAdmin | None = None) -> Callable`；`POST /api/settings/sites`、`PATCH /api/settings/sites/{id}`；`create_app_from_env` 只在显式 `RADAR_SITE_ADMIN_DATABASE_URL` 下启用写接口，无 writer 回退。设置读取在 Task 8 提供。

- [ ] **Step 1: 写失败测试。** `test_admin_write_requires_basic_auth_and_same_origin`、`test_cross_site_or_missing_origin_rejected`、`test_private_and_cross_domain_url_rejected`、`test_homepage_host_cannot_be_edited`、`test_admin_role_cannot_write_events`、`test_missing_admin_dsn_disables_writes`；合法新增/改名/Sitemap/暂停/恢复持久成功。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_site_admin_web.py tests/platform_integration/test_site_admin_permissions.py`，确认新增用例失败。
- [ ] **Step 3: 实现窄接口。** Basic Auth 后限制 JSON body、校验 Origin 与可信 Host/预览域名，拒绝缺失或不匹配来源；校验 URL、主页域名不可变；无删除/手动抓取端点。错误不得回显数据库 URL 或凭据。
- [ ] **Step 4: 运行上述测试及** `python -m pytest -q tests/platform/test_web.py tests/platform_integration/test_readonly.py`，确认隔离数据库权限和旧只读 API 未回退。
- [ ] **Step 5: 提交** `feat: manage sites with narrow database role`。

### Task 7: 北京时间总览和每日新词查询

**Files:** Modify `radar/platform/{queries,web}.py`, `tests/platform/test_web.py`, `tests/platform_integration/test_readonly.py`; Create `tests/platform_integration/test_daily_queries.py`。

**Interfaces:** `ReadQueries.overview(day: date, now: datetime) -> dict`；`ReadQueries.daily_terms(day: date, *, cursor: str | None = None, limit: int = 50) -> dict`；`ReadQueries.daily_source_status(day: date, now: datetime) -> dict`。API `GET /api/overview?date=YYYY-MM-DD`、`GET /api/daily-terms?date=...&cursor=...`，无日期默认北京时间今天，未来日期 400。

- [ ] **Step 1: 写失败测试。** `test_overview_day_boundary_and_missing_state` 在北京时间午夜两侧种词、证据、竞品事件，断言五指标同日切换、成功 0 与未采集不同；`test_daily_terms_merges_sources_per_first_seen_term`；`test_future_date_rejected`；`test_research_card_keeps_all_evidence`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform_integration/test_daily_queries.py tests/platform/test_web.py`，确认新增用例失败。
- [ ] **Step 3: 实现查询/API。** 所选日均用同一 `[day_start,next_day_start)` 北京时间范围；新词一词一行、来源合并，线索数按证据条数；来源基线数不进总览/新词；`/api/terms/{id}` 保留。
- [ ] **Step 4: 运行上述测试且无 skip**，与 dev Neon 指定日期 SQL 逐项核对五个数字。
- [ ] **Step 5: 提交** `feat: add date-aware daily keyword queries`。

### Task 8: 多站点汇总、单站明细和设置状态

**Files:** Modify `radar/platform/{queries,web}.py`; Create `tests/platform_integration/test_competitor_queries.py`, `tests/platform/test_competitor_web.py`。

**Interfaces:** `ReadQueries.competitor_sites(filters: dict[str,str], *, page: int = 1, limit: int = 20) -> dict`；`ReadQueries.competitor_events(site_id: str, filters: dict[str,str], *, page: int = 1, limit: int = 50) -> dict`；`ReadQueries.settings_status(now: datetime) -> dict`。API `GET /api/competitors`、`GET /api/competitors/{id}/events`、`GET /api/settings/status`。

- [ ] **Step 1: 写失败测试。** `test_large_competitor_pages_match_counts` 种 20 站及单站 1,000 事件，断言汇总与 50/页详情一致；搜索站名、URL 路径、状态、时间、新增/移出及“只看有变化”过滤；`test_failed_and_baseline_states_distinct`；`test_settings_has_gh_hf_and_site_baselines` 核对最近成功/最近尝试/本次新增；“移出”文案不含“网页已删除/404”。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform_integration/test_competitor_queries.py tests/platform/test_competitor_web.py`，确认新增用例失败。
- [ ] **Step 3: 实现参数化 SQL 与只读 API。** 汇总先按站点且最近变化排序，不传全量 URL；单站仅传一页；状态来自最近尝试和最近成功两个时间；设置状态复用现有来源运行记录并带站点基线。
- [ ] **Step 4: 运行上述测试且无 skip**；核对时间/分页索引的查询计划，不随事件总量把全表搬到浏览器。
- [ ] **Step 5: 提交** `feat: read paged competitor events and source health`。

### Task 9: 一个极简网站完成三个功能页

**Files:** Modify `radar/platform/templates/index.html`, `radar/platform/static/{app.js,app.css}`, `tests/platform/test_web.py`; Create `tests/e2e/test_workbench.py` 及所需浏览器测试配置/开发依赖锁文件。

**Interfaces:** 左侧一级入口严格 `总览/关键词看板/设置`；看板顶部仅 `新词/竞品`；刷新保持页签；总览日期只影响总览；`/terms/{id}` 保留并能返回新词；V1 无 Trends 页面或采集按钮。

- [ ] **Step 1: 写失败浏览器测试。** `test_sidebar_and_tabs_exact_labels`、`test_overview_date_changes_five_values`、`test_daily_terms_actions_and_no_baselines`、`test_competitor_sites_then_url_rows`（路径、完整 URL、发现时间、原始链接、50/页）、`test_settings_add_pause_resume_and_status`、`test_narrow_layout_and_safe_external_text`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/e2e/test_workbench.py`，确认新增用例失败；本地 WSGI/浏览器测试只连接隔离 schema。
- [ ] **Step 3: 实现页面。** 沿用当前 Term Signal 色彩字体，去掉大 Hero 和新词页 `SOURCE PULSE`；总览只日期与五指标；新词直接今日更新和逐条名称/来源/发现时间/出处/研究卡；竞品先站点再 URL；设置输入和所有基线状态。每页数据服务端分页，窄屏侧栏可折叠，文字使用 `textContent`，外链安全校验。
- [ ] **Step 4: 运行浏览器和** `python -m pytest -q tests/platform/test_web.py`；检查桌面、约 390px 窄屏、长 URL、首次建档、成功零变化、失败与无匹配结果。
- [ ] **Step 5: 提交** `feat: show unified term signal workbench`。

### Task 10: 免费调度、预览部署和总体验收

**Files:** Create `.github/workflows/free-platform.yml`, `tests/platform/test_workflow_policy.py`, `docs/verification/2026-10-21-unified-v1.md`; Modify `docs/operations/platform.md`, `docs/FORK.md`, 必要的 CI 配置。

**Interfaces:** Actions `workflow_dispatch(kind=sources|sites)`；UTC 0/8/16 点各运行三来源、每日独立运行站点；`FREE_RADAR_ENABLED` 默认 off，启用只限通过预览验收后的指定环境。

- [ ] **Step 1: 写失败政策测试。** `test_only_free_collect_is_scheduled`、`test_paid_workflow_remains_disabled`、`test_app_requires_read_and_site_admin_dsn_separately`、`test_collector_secret_never_used_by_web_factory`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_workflow_policy.py`，确认新增用例失败。
- [ ] **Step 3: 加免费工作流和手册。** Python 3.12、现有依赖，只传 writer 和 GitHub token；定时事件受 `FREE_RADAR_ENABLED` 门控，人工触发只允许受信分支及 dev Neon 凭据，不能让不可信 PR 读取 secrets。任务状态只在 Neon；Vercel 预览只配 reader + site-admin + Basic Auth，不配 writer/migrator。旧上游工作流不启用。故障返回非零并保留可读日志。
- [ ] **Step 4: 跑验收关卡。** `python -m pytest -q tests` 原项目/平台/隔离 Neon/浏览器都通过且无 skip；wheel 安装与 Vercel 入口验证；开发分支人工触发真实第二次来源和首次+后续 Sitemap 运行，记录 run、版本、计数；预览网页逐项核对 SQL、权限、桌面/窄屏。缺失真实第二日结果时明示“尚未验证”，不能用假数据宣称已连续两日运行。
- [ ] **Step 5: 提交** `chore: schedule and verify unified free radar`；在 `docs/verification/2026-10-21-unified-v1.md` 留实际命令、时间、预览地址和结论。正式环境启用另行确认；回退先关闭免费 workflow，再回退网页，保留新表和旧 Trends 表。

## 阶段停点

Task 1 先证明“一个主包”可运行且上游行为未坏；Task 2 证明新词能持续采；Task 3～5 证明竞品安全完整且差分真实；Task 6～8 证明写入边界与查询一致；Task 9 验收原型；Task 10 才接调度和预览。每项先红后绿、独立提交；前一关未过不进入下一关。这个计划替代 [旧的并行平台计划](2026-10-21-term-signal-v1.md)，旧计划只作历史记录，不得继续执行。
