# Term Signal 免费研究工作台 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 GitHub/HF 新词、每日 Sitemap 增减和可管理站点的设置，整合进一个自动运行的 Term Signal 工作台。

**Architecture:** 保留 `radar_platform` 的 Python 采集、Neon、WSGI/Vercel 和原生 JS，不另起前后端。Sitemap 配置/快照/事件与关键词证据分表；采集任务在 GitHub Actions 运行，网页仅读取结果，设置通过单独限权数据库角色写站点配置。先在现有 `dev-free-platform` Neon 分支及 Vercel 预览验证，再考虑正式启用。

**Tech Stack:** Python 3.12、psycopg 3、Neon Postgres、GitHub Actions、Vercel WSGI、HTML/CSS/原生 JS、pytest；浏览器验收使用 Playwright。

**Spec:** [2026-10-21-free-radar-sitemap-v1-requirements.md](../specs/2026-10-21-free-radar-sitemap-v1-requirements.md)。实施前完整阅读；以其 US-001～010 和验收口径为准。

## Global Constraints

- 继续复用 `keyword-detective` 项目的 `dev-free-platform` Neon 分支；不创建第二个项目，不改生产库。迁移只用直接连接、显式命令，运行时不建表。
- V1 不使用付费 API，不从竞品 URL 推断关键词，不抓网页正文，不把“移出 Sitemap”写成“页面已下线”。
- GitHub/HF 每 8 小时、Sitemap 每日；首次完整 Sitemap 只建基线，0 个增减事件。
- 单站最多 20 份 Sitemap 文档、20,000 个 URL；任何分片失败、空集、解析错误、超限都不推进旧基线。
- 全部日期统计以 `Asia/Shanghai` 自然日计；区分成功零变化与未采集，首页日期不能选未来。
- 看板普通查询继续 `RADAR_READ_DATABASE_URL`；网页设置仅用新 `RADAR_SITE_ADMIN_DATABASE_URL`，不能获得 `RADAR_WRITE_DATABASE_URL`。浏览器不接触任何数据库 URL。
- 网站和外链文本不得作为 HTML 注入；外部请求在保存和实际连接时都校验地址、重定向及解析 IP；设置写入防跨站提交。
- 旧上游 `.github/workflows/radar.yml` 保持关闭；新免费工作流独立创建，不复用其付费入口。
- 数据库集成测试必须使用隔离的 `RADAR_TEST_DATABASE_URL` 与 `RADAR_TEST_ALLOWED_HOST`；测试 skip 不算通过。真实试点站点先建档，再在预览环境验证差分。

## Review Focus

1. DNS 重绑定/重定向至私网或云元数据 IP：即使保存时是公网域名，实际连接也不得访问内网（Task 3 的 `test_connection_pins_public_ip_and_rechecks_redirect`）。
2. Sitemap 索引部分失败或空结果：不得产生海量假“移出”，旧 URL 集合与版本原封不动（Task 4 的 `test_incomplete_snapshot_keeps_state_and_events`）。
3. 北京时间零点前后与夏令时无关的日期边界：五个总览指标必须使用同一半开区间（Task 6 的 `test_overview_all_metrics_use_selected_shanghai_day`）。
4. Basic Auth 在跨站表单/请求中被浏览器自动携带：无同源校验或写入令牌的设置 POST 必须拒绝（Task 5 的 `test_cross_origin_admin_write_rejected`）。
5. 站点数/事件数放大后的列表：20 站、单站 1,000 事件仍在服务端筛选和每页 50 条分页，汇总/详情数字一致（Task 7 的 `test_competitor_filters_and_pagination_at_scale`）。

---

## File map and contracts

| 文件 | 单一职责 |
|---|---|
| `schema/platform/004_sitemap.sql`, `005_site_roles.sql` | 站点、当前 URL、事件、快照状态表及显式权限；已有 001～003 不改 checksum |
| `radar_platform/site_store.py` | `SiteStore(dsn, schema)`：采集事务、站点列表、状态及事件提交 |
| `radar_platform/site_admin.py` | `SiteAdmin(dsn, schema)`：仅增改/暂停/恢复 `radar_sites` |
| `radar_platform/adapters/sitemap.py` | `discover_and_collect(site, http) -> SitemapResult`：robots/Sitemap 解析、完整性检查、URL 规范化 |
| `radar_platform/http.py` | 与现有预算客户端共用的固定公网 IP 连接、每次跳转再校验 |
| `radar_platform/schedule.py`, `radar_platform/__main__.py`, `radar_platform/runner.py` | 8 小时与每日任务入队、领取、隔离执行及 CLI |
| `radar_platform/queries.py`, `radar_platform/web.py` | 北京时间只读聚合/API；管理 API 的认证、限权和同源检查 |
| `radar_platform/templates/index.html`, `radar_platform/static/{app.js,app.css}` | 左侧导航、日期、两个看板页签、设置及研究卡 |
| `.github/workflows/free-platform.yml`, `docs/operations/platform.md` | 免费定时任务和可恢复的预览/启用操作 |
| `tests/platform/`, `tests/platform_integration/`, `tests/e2e/` | 离线、隔离 Neon、浏览器验收 |

约定：站点身份是稳定 UUID；`radar_sites.homepage_host` 不可编辑。`SiteStore.commit_complete(site_id: UUID, run_key: str, scheduled_for: datetime, urls: set[str], observed_at: datetime) -> dict[str, int]` 是唯一推进基线并写事件的事务入口。`run_key` 为 `site:<uuid>:<UTC scheduled slot>`；`radar_site_state.last_run_key/last_slot_at` 阻止同周期重复提交或较旧任务覆盖新快照；下一周期即使 URL 集合不变，运行记录可更新但事件为 0。所有 API 由 Basic Auth 保护，管理 API 另外要求同源校验，且只授予站点配置表权限。

### Task 1: 跑通现有来源第二次采集与 8 小时任务入口

**Files:** Create `radar_platform/schedule.py`, `tests/platform/test_schedule.py`; Modify `radar_platform/{__main__,runner}.py`, `tests/platform/test_runner.py`。

**Interfaces:** `seed_source_jobs(repo: Repository, now: datetime) -> int` 按北京时间对应的 UTC 0/8/16 点幂等入队三个独立来源；`run_due_sources(repo: Repository, cfg: PlatformConfig, now: datetime, *, max_jobs: int) -> RunSummary` 复用 `run_source` 和现有 lease。

- [ ] **Step 1: 写失败测试。** `test_three_sources_each_eight_hour_slot_once` 断言一个周期只产生三项、重复 seed 为 0；`test_second_source_run_keeps_baseline_and_no_duplicate_terms` 断言第二周期有运行记录、同槽重跑不增词；`test_one_source_failure_does_not_skip_other_sources` 断言隔离失败。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_schedule.py tests/platform/test_runner.py`，确认新增用例失败。
- [ ] **Step 3: 实现上述两个签名与 CLI** `python -m radar_platform tick --kind sources --max-jobs 3`；只使用 `RADAR_WRITE_DATABASE_URL`，无值即失败；不调用上游 `radar/` 或付费接口。
- [ ] **Step 4: 跑上述测试及** `python -m pytest -q tests/platform_integration/test_ingest.py`；隔离 Neon 环境变量缺失时先配置，不能把 skip 当通过。随后在开发分支执行第二次真实采集，记录三来源运行时间、基线和新增词数于 `docs/verification/2026-10-21-v1.md`。
- [ ] **Step 5: 提交** `feat: schedule free source collection`。

### Task 2: 独立保存多个竞品站点及最小权限

**Files:** Create `schema/platform/{004_sitemap,005_site_roles}.sql`, `radar_platform/{site_store,site_admin}.py`, `tests/platform_integration/test_sites.py`; Modify `tests/platform_integration/test_migrations.py`, `docs/operations/platform.md`。

**Interfaces:** `SiteAdmin.add_site(name: str, homepage_url: str, sitemap_url: str | None) -> UUID`；`SiteAdmin.update_site(site_id: UUID, *, name: str, sitemap_url: str | None, enabled: bool) -> None`；`SiteStore.list_enabled_sites() -> list[dict]`；`SiteStore.commit_complete(...) -> dict[str, int]`。运行尝试沿用现有 `radar_jobs/radar_runs`，由 Task 4 的 runner 写入。

- [ ] **Step 1: 写失败集成测试。** `test_site_baseline_and_diff_are_atomic`：首次 `{a,b}` 为 0/0，第二次 `{b,c}` 为 1/1，第三次同一 `run_key` 不增加版本/事件；较旧 slot 重试也不回退；移出后再出现记新增；`test_sites_are_isolated` 验证两个站独立快照；`test_site_admin_cannot_write_events_or_terms` 验证数据库角色拒绝越权。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform_integration/test_sites.py`，确认新增用例失败。
- [ ] **Step 3: 实现迁移和存储。** `radar_sites` 保存 UUID/名称/主页/固定 host/可选 sitemap/enabled；`radar_site_state` 保存版本、URL 数、最近成功时间、最近 run key/slot；`radar_site_urls` 以 `(site_id,url)` 为主键存当前集合；`radar_site_events` 保存 `(site_id,run_key,event_type,url,discovered_at)` 并唯一约束。事件类型仅 `added|removed`。事务用站点行锁保护并发与空集；同一 `run_key` 重试须返回既有提交结果，旧 slot 不得覆盖新快照。`005` 对 reader 授予只读所需表，对 writer 授予站点数据 DML，对新 `radar_platform_site_admin` 仅授予 `radar_sites` 的 SELECT/INSERT/UPDATE；无 DELETE、无默认全表授权。
- [ ] **Step 4: 在隔离 Neon schema 执行** `python -m pytest -q tests/platform_integration/test_migrations.py tests/platform_integration/test_sites.py`，确认无 skip；在开发分支以 SQL 建立最小权限 site-admin 登录角色并轮换密码，用 migrator 直接连接应用新增迁移，复跑应显示 applied=[]，核对旧表计数不变。
- [ ] **Step 5: 提交** `feat: persist competitor sitemap state and roles`。

### Task 3: 安全且完整地读取 robots 与 Sitemap

**Files:** Create `radar_platform/adapters/sitemap.py`, `tests/platform/test_sitemap.py`; Modify `radar_platform/http.py`, `tests/platform/test_http.py`。

**Interfaces:** `SitemapResult(status: Literal['complete','incomplete'], urls: set[str], documents: int, error: str | None)`；`discover_and_collect(site: Mapping[str, Any], http: HttpClient) -> SitemapResult`。不在 adapter 内写数据库。

- [ ] **Step 1: 写失败测试。** 普通 `urlset`、多层 `sitemapindex`、robots 声明发现、重复 URL/默认端口/片段保守规范化、`lastmod` 变化不产生 URL 差分；`test_connection_pins_public_ip_and_rechecks_redirect` 用假 resolver/transport 验证私网解析与跳转均被拒；`test_empty_invalid_or_over_budget_sitemap_is_incomplete` 覆盖空集、损坏 XML、21 份文档、20,001 URL、5 MiB 响应上限；`test_robots_disallow_or_crawl_delay_respected` 覆盖拒抓与延迟。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_sitemap.py tests/platform/test_http.py`，确认新增用例失败。
- [ ] **Step 3: 实现 adapter 与连接保护。** 仅 HTTP(S) 且与站点 host 同源的 robots/Sitemap/重定向；每个目标连接使用已校验的公网 IP 发起 TCP，TLS 仍以原域名校验证书及 SNI，避免 DNS 预检后重解析；继承 `HttpClient` 请求/时间预算。XML 只收 `<loc>`，限制文档数/URL 数，不抓 URL 正文。若 robots 不允许或未发现 Sitemap，返回 incomplete 并给设置页状态。
- [ ] **Step 4: 运行** `python -m pytest -q tests/platform/test_sitemap.py tests/platform/test_http.py`；用 `aiphotoeditor.com` 只读探测验证能读到完整非空集合，不写事件。
- [ ] **Step 5: 提交** `feat: safely collect complete sitemaps`。

### Task 4: 每日采集、差分与失败保护

**Files:** Modify `radar_platform/{schedule,runner,__main__,site_store}.py`; Create `tests/platform/test_site_runner.py`, `tests/platform_integration/test_site_ingest.py`。

**Interfaces:** `seed_site_jobs(repo: Repository, sites: SiteStore, now: datetime) -> int` 按站点+每日 UTC slot 入队；`run_due_sites(repo: Repository, sites: SiteStore, now: datetime, http_factory, *, max_jobs: int) -> RunSummary` 调用 Task 3，只在 complete 时调用 Task 2 的 `commit_complete`。

- [ ] **Step 1: 写失败测试。** `test_first_run_builds_baseline_without_events`、`test_three_additions_two_removals_then_zero`、`test_incomplete_snapshot_keeps_state_and_events`（失败分片/空集/预算）、`test_one_site_failure_does_not_block_next`、`test_pause_prevents_new_jobs_but_keeps_history`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_site_runner.py tests/platform_integration/test_site_ingest.py`，确认新增用例失败。
- [ ] **Step 3: 实现两个签名及** `python -m radar_platform tick --kind sites --max-jobs 20`；状态由数据库站点配置而非 `config/platform.json` 的静态列表决定，保存配置不即时抓取；成功/失败/不完整通过现有 `Repository.finish_job/fail_job` 写 `radar_runs`，失败/不完整不能触及成功快照。若 `commit_complete` 后进程中断，同 `run_key` 重试只补运行记录，不重复写事件。错过日期不伪造过去页面事件。
- [ ] **Step 4: 运行上述测试**，确保集成测试无 skip；在开发分支把 `aiphotoeditor.com` 作为首个站点建档，核对实际 URL 数且事件为 0；重复同周期重跑仍为 0，并把证据写入验证文档。
- [ ] **Step 5: 提交** `feat: run daily competitor sitemap diff`。

### Task 5: 只有设置可以写站点

**Files:** Modify `radar_platform/{web,auth}.py`, `tests/platform/test_web.py`; Create `tests/platform/test_site_admin_web.py`, `tests/platform_integration/test_site_admin_permissions.py`。

**Interfaces:** `create_app(queries: ReadQueries, *, username: str, password_sha256: str, site_admin: SiteAdmin | None = None) -> Callable`；`POST /api/settings/sites`、`PATCH /api/settings/sites/{id}`。只读设置数据由 Task 7 的 `GET /api/settings/status` 提供。`create_app_from_env` 只在配置 `RADAR_SITE_ADMIN_DATABASE_URL` 时启用管理写入，绝不回退到 writer。

- [ ] **Step 1: 写失败测试。** `test_unauthenticated_admin_write_rejected`、`test_cross_origin_admin_write_rejected`、`test_invalid_private_or_cross_domain_url_rejected`、`test_edit_cannot_change_homepage_host`、`test_read_role_cannot_mutate_and_admin_role_cannot_write_events`、`test_missing_admin_dsn_keeps_get_only`；合法添加、改名、Sitemap、暂停/恢复返回持久结果。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_site_admin_web.py tests/platform_integration/test_site_admin_permissions.py`，确认新增用例失败。
- [ ] **Step 3: 实现窄写入 API。** Basic Auth 后对 POST/PATCH 校验 `Origin` 与 `Host`/受信代理域名，拒绝缺失或不匹配来源；接受 `application/json`、限制 body 字节数、校验 URL/站点 host，不信任用户给的重定向。拒绝永久删除与手动抓取端点；CSRF 检查同时在预览域名/本地端口验收。管理错误不得回显连接串。
- [ ] **Step 4: 运行上述测试及** `python -m pytest -q tests/platform/test_web.py tests/platform_integration/test_readonly.py`，确保旧只读边界不回退；在隔离库用 site-admin 角色验证只可改 `radar_sites`。
- [ ] **Step 5: 提交** `feat: add owner-only competitor settings API`。

### Task 6: 日期总览与今日新词 API

**Files:** Modify `radar_platform/{queries,web}.py`, `tests/platform/test_web.py`, `tests/platform_integration/test_readonly.py`; Create `tests/platform_integration/test_daily_queries.py`。

**Interfaces:** `ReadQueries.overview(day: date, now: datetime) -> dict`；`ReadQueries.daily_terms(day: date, *, cursor: str | None = None, limit: int = 50) -> dict`；`ReadQueries.daily_source_status(day: date, now: datetime) -> dict`。API `GET /api/overview?date=YYYY-MM-DD`、`GET /api/daily-terms?date=...&cursor=...`；省略日期取北京时间今天，未来日期 400。

- [ ] **Step 1: 写失败测试。** `test_overview_all_metrics_use_selected_shanghai_day` 在 00:00 北京时间两侧种数据，断言五指标同步切换；`test_successful_zero_differs_from_not_collected`；`test_daily_terms_one_row_per_first_seen_term_with_all_source_tags`；`test_future_date_rejected`；旧 `/api/terms/{id}` 研究卡仍返回所有证据。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform_integration/test_daily_queries.py tests/platform/test_web.py`，确认新增用例失败。
- [ ] **Step 3: 实现查询。** 五指标分别为当天新词、当天证据、有事件的站点、新增 URL、移出 URL；用同一 `[day_start, next_day_start)` 时间范围。新词列表按 `first_seen_at`，同一词来源合并；“今日线索数”按证据条数，不能误等于列表行数。运行状态区分成功 0/未运行/失败，来源健康细节留给设置。
- [ ] **Step 4: 运行上述测试且无 skip**，与开发库指定日期 SQL 计数逐项对照。
- [ ] **Step 5: 提交** `feat: expose date-aware overview and daily terms`。

### Task 7: 竞品汇总与单站事件 API

**Files:** Modify `radar_platform/{queries,web}.py`; Create `tests/platform_integration/test_competitor_queries.py`, `tests/platform/test_competitor_web.py`。

**Interfaces:** `ReadQueries.competitor_sites(filters: dict[str, str], *, page: int = 1, limit: int = 20) -> dict`；`ReadQueries.competitor_events(site_id: str, filters: dict[str, str], *, page: int = 1, limit: int = 50) -> dict`；`ReadQueries.settings_status(now: datetime) -> dict`。API `GET /api/competitors`、`GET /api/competitors/{id}/events`、`GET /api/settings/status`；服务端过滤日期范围、站点名/URL 路径、状态与事件类型。

- [ ] **Step 1: 写失败测试。** `test_competitor_filters_and_pagination_at_scale` 种 20 站/单站 1,000 事件，断言服务端 20 站一页、50 事件一页及汇总一致；`test_removed_label_never_implies_404`；`test_failed_baseline_and_no_match_are_distinct_states`；`test_settings_status_reports_gh_hf_and_site_baselines`。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform_integration/test_competitor_queries.py tests/platform/test_competitor_web.py`，确认新增用例失败。
- [ ] **Step 3: 实现查询/API。** 按最近变化时间排序；搜索和筛选在 SQL 层完成，参数化查询；站点汇总不下发全站 URL，详情只给一页；设置状态复用现有 `sources()` 并加入站点状态和最近尝试。
- [ ] **Step 4: 运行上述测试**，用查询计划核对分页/时间索引被使用，隔离库无 skip。
- [ ] **Step 5: 提交** `feat: expose paged competitor and settings data`。

### Task 8: 极简工作台与设置页面

**Files:** Modify `radar_platform/templates/index.html`, `radar_platform/static/{app.js,app.css}`, `tests/platform/test_web.py`; Create `tests/e2e/test_workbench.py`，更新 `requirements-dev.in/.txt`（若仓库还没有则同任务创建）。

**Interfaces:** 左侧三个一级导航 `总览/关键词看板/设置`；看板右侧顶部仅 `新词/竞品`；URL 或 hash 记住当前页签并保留 `/terms/{id}`；日期仅控制总览。

- [ ] **Step 1: 写失败浏览器测试。** `test_overview_date_updates_five_values_and_blocks_future`、`test_daily_terms_keep_source_and_research_card_actions`、`test_competitor_sites_then_fifty_url_events`、`test_settings_add_edit_pause_resume_and_status`、`test_desktop_and_narrow_navigation`。断言新词和总览没有基线卡；设置有基线；退出详情能回到新词；文本/XSS 和 `javascript:` URL 不执行。
- [ ] **Step 2: 运行** `python -m pytest -q tests/e2e/test_workbench.py`，确认新增用例失败；固定浏览器与本地 WSGI fixture，测试数据只进隔离 schema。
- [ ] **Step 3: 实现页面。** 沿用现有色彩与字体；移除首页大 Hero 和 `SOURCE PULSE`；总览只有日期+五指标；新词直接今日概览+行列表；竞品先站点、后单站事件；设置集中站点表单和全部来源状态。多条信息时分页，不在浏览器一次载入 1,000 URL。窄屏折叠侧栏但维持顺序，外链沿用 `safeHttpUrl`/`textContent`。
- [ ] **Step 4: 运行浏览器测试及** `python -m pytest -q tests/platform/test_web.py`；手工看桌面与约 390px 窄屏，检查长 URL 不撑破布局及五种空/错误状态。
- [ ] **Step 5: 提交** `feat: redesign term signal workbench`。

### Task 9: 免费调度、预览部署和真实验收

**Files:** Create `.github/workflows/free-platform.yml`, `tests/platform/test_workflow_policy.py`, `docs/verification/2026-10-21-v1.md`；Modify `docs/operations/platform.md`, `docs/FORK.md`。

**Interfaces:** `workflow_dispatch` 可选 `sources|sites`；定时 0/8/16 UTC 跑三来源、每日单独跑站点；只有新工作流拿 writer 凭据，Vercel 预览只拿 reader+site-admin；`FREE_RADAR_ENABLED` 默认关闭，验证后再开。

- [ ] **Step 1: 写失败政策测试。** `test_free_workflow_has_only_free_entrypoint_and_separate_schedules`、`test_web_env_never_falls_back_to_collector_writer`、`test_old_paid_workflow_stays_off`；Vercel 实际环境凭据另在 Step 4 核查，不以仓库测试代替。
- [ ] **Step 2: 运行** `python -m pytest -q tests/platform/test_workflow_policy.py`，确认新增用例失败。
- [ ] **Step 3: 加工作流/操作手册。** 只用 Python 3.12、现有锁定依赖、GitHub token 与 `RADAR_WRITE_DATABASE_URL`；任务状态在 Neon，不用 Actions cache 做事实来源。配置预览环境 `RADAR_READ_DATABASE_URL` 与新限权 site-admin 角色；不向 Vercel 注入 writer/migrator。运行失败非零并保留可读日志。
- [ ] **Step 4: 验证三个关卡。** ① `python -m pytest -q tests` 离线+隔离 Neon+浏览器均通过且无 skip；② 在开发分支人工触发两轮来源和两轮 Sitemap 日周期，核对真实 run/基线/零变化，不篡改 event 时间；③ 打开 Vercel 预览，比较指定日期五项数字与 SQL，验证设置写入、只读角色拒写、错误状态及窄屏。记录实际命令/时间/截图/预览 URL/结果；任一关未通过不得启用生产调度。
- [ ] **Step 5: 提交** `chore: schedule and verify free radar preview`；提供生产启用前检查单与回退：先关 `FREE_RADAR_ENABLED`、回退网页部署，保留历史表并排查，任何正式环境变更另行确认。

## 交付顺序与停点

Task 1 验证现有新词链路持续可跑；Task 2～4 验证竞品真实数据链；Task 5～7 验证安全与查询；Task 8 验证工作台；Task 9 才接自动运行和预览。每个任务先红后绿、保留独立提交；关键验证未过就停在当前节点，不跳到下一任务。正式生产迁移和启用不包含在本计划的自动执行授权内，需看完预览证据再决定。
