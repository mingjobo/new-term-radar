# 公开版自动关键词雷达实施计划

> **供执行者使用：** 按任务逐项实施本计划时，必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 技能。任务进度使用 `- [ ]` 复选框记录。

**目标：** 将现有 `new-term-radar` 工作台发布为免登录网站，并按已确定的免费采集时间表，持续收集 GitHub、Hugging Face 和竞品站点地图的数据。

**架构：** 沿用现有 Python WSGI 网站、原生网页、Neon 数据表和采集程序。GitHub Actions 定时运行采集程序并写入 Neon；Vercel 负责读取和展示数据，且只通过单独的服务端数据库连接修改竞品站点配置。浏览器拿不到数据库凭据。

**技术栈：** Python 3.10–3.12、WSGI、psycopg 3.3.6、Neon PostgreSQL、原生 HTML/CSS/JavaScript、pytest、Playwright/Chrome、GitHub Actions、Vercel。

**设计文档：** `docs/superpowers/specs/2026-10-22-public-auto-radar-simplification-design.md`

## 全局约束

- 网站没有账号、Basic Auth、密码、口令、登录会话或用户表；访客可以查看数据，也可以修改竞品设置。
- `RADAR_READ_DATABASE_URL`、`RADAR_SITE_ADMIN_DATABASE_URL`、`RADAR_WRITE_DATABASE_URL` 和数据库迁移凭据只存在服务端；浏览器 JavaScript 不能接触数据库连接地址。
- 保留同源写入检查、公开网址校验、JSON 和请求体大小限制、重复站点拦截、站点地图完整性检查，以及参数化 SQL。
- GitHub/HF 每天在 UTC `00:00`、`08:00`、`16:00` 定时采集；竞品站点地图在 UTC `01:30` 采集；每次最多处理 20 个竞品任务。
- 来源采集失败或不完整时，不能推进来源基线；站点地图采集失败或不完整时，不能生成“页面消失”事件，也不能替换上一次完整的 URL 集合。
- 本阶段不加入 Google Trends 历史数据、付费 API、页面内容变化对比、网页手动采集按钮、删除历史数据操作或新前端框架。
- 不删除已有的 `radar_*` 表或旧 Trends 表，不改写已执行的数据库迁移文件，不强制推送 `main`，也不让可能删除数据的集成测试连接生产 Neon。

## 重点复核的问题

- 未登录访问 `/`、静态文件和只读接口时，应正常返回内容，且不出现 `WWW-Authenticate` 登录提示；任务 1 验证。
- 公开的设置页应允许同源请求修改竞品；缺少来源信息或跨站请求仍应被拒绝；任务 1 验证。
- 未配置竞品设置专用数据库连接时，应禁止设置写入，且不能改用采集程序的数据库凭据；任务 1 验证。
- 从 `main` 手动运行采集时，必须使用 `free-radar-production` 环境；在 `FREE_RADAR_ENABLED=true` 之前，定时采集保持关闭；任务 2 验证。
- 采集失败、不完整，或站点数量超过单次 20 个任务的上限时，页面应显示未采集，而不是确认“零变化”或误报“页面消失”；任务 2 和任务 6 结合现有采集测试、任务配置检查和生产运行记录验证。

---

### 任务 1：取消网页登录，保留设置校验

**涉及文件：**
- 修改：`radar/platform/web.py`
- 修改：`radar/platform/auth.py`
- 修改：`radar/platform/commands.py`
- 修改：`tests/platform/test_web.py`
- 修改：`tests/platform/test_site_admin_web.py`
- 修改：`tests/platform/test_workflow_policy.py`
- 修改：`tests/platform/test_package_merge.py`
- 修改：`tests/e2e/test_workbench.py`

**接口约定：**
- 实现：`create_app(queries: ReadQueries, *, site_admin: SiteAdmin | None = None, allowed_origins: set[str] | None = None) -> Callable`
- 实现：`create_app_from_env(environ: Mapping[str, str] | None = None) -> Callable`。它必须读取 `RADAR_READ_DATABASE_URL`；启用设置写入时，还必须读取 `RADAR_SITE_ADMIN_DATABASE_URL` 和 `RADAR_WEB_ALLOWED_ORIGINS`。不再要求网页用户名和密码。
- 保留：`trusted_same_origin(origin: str | None, host: str | None, allowed_origins: set[str]) -> bool`。

- [ ] **步骤 1：先写免登录访问测试。** 在 `test_web.py` 中添加 `test_public_routes_need_no_credentials`：不带 Authorization 请求头访问 `/`、`/api/overview`、`/api/daily-terms`、`/api/competitors`、`/api/settings/status` 和 `/static/app.css`，均应返回 `200`，且响应中没有 `WWW-Authenticate`。同时修改测试夹具，让它使用新的 `create_app` 参数。
- [ ] **步骤 2：用测试固定公开写入边界。** 在 `test_site_admin_web.py` 中将写入测试改名为 `test_admin_write_is_public_but_requires_same_origin`：不带登录凭据的同源 POST 应返回 `201`；缺少来源或跨站请求应返回 `403`；JSON、请求大小、重复站点、网址安全校验应与原来一致；缺少 `RADAR_SITE_ADMIN_DATABASE_URL` 时应返回 `405`，不能回退到 `RADAR_WRITE_DATABASE_URL`。
- [ ] **步骤 3：运行针对性测试，确认旧登录行为使新测试失败。** 运行 `python -m pytest -q tests/platform/test_web.py tests/platform/test_site_admin_web.py tests/platform/test_workflow_policy.py tests/platform/test_package_merge.py tests/e2e/test_workbench.py`。预期失败原因：旧代码仍要求 Basic Auth 参数、返回登录提示，或仍要求网页密码环境变量。
- [ ] **步骤 4：实现免登录网站。** 在 `web.py` 中移除 `BasicAuth` 初始化和返回 401 的分支；移除 `username`、`password_sha256` 参数及对应环境变量检查；删除已无用途的 `BasicAuth` 类和导入，保留同源校验。同步修改 `serve` 命令的帮助和运行提示，不再把网站称作只读网站。
- [ ] **步骤 5：更新测试夹具。** 移除测试里生成的密码哈希、Authorization 辅助函数和 Playwright 的 `http_credentials`。内容安全策略（CSP）、安全链接显示、写入来源检查和数据库凭据隔离的断言保持不变。
- [ ] **步骤 6：重新运行针对性测试。** 运行步骤 3 的同一命令。预期全部通过，包含真实 Chrome 浏览器测试。
- [ ] **步骤 7：提交。** 只提交任务 1 的代码和测试，提交说明为 `feat: make keyword radar publicly accessible`。

### 任务 2：让现有定时任务可以安全地用于正式环境

**涉及文件：**
- 修改：`.github/workflows/free-platform.yml`
- 修改：`tests/platform/test_workflow_policy.py`

**接口约定：**
- 使用：`python -m radar collect --kind sources|sites --max-jobs N` 和仅保存在服务端的 `RADAR_WRITE_DATABASE_URL`。
- 实现三种运行方式：从开发分支手动运行时使用 `free-radar-dev`；从 `main` 手动运行时使用 `free-radar-production`；从 `main` 定时运行时也使用 `free-radar-production`，但受启用开关控制。

- [ ] **步骤 1：先写会失败的任务配置测试。** 断言手动运行只接受 `refs/heads/codex/free-keyword-platform` 和 `refs/heads/main`；`main` 的手动和定时运行都选用 `free-radar-production`；只有定时运行要求 `FREE_RADAR_ENABLED == 'true'`。同时固定准确的定时时间、竞品 `MAX_JOBS=20`、来源 `MAX_JOBS=3`、25 分钟超时，以及任务不能获取网页读取、设置管理、数据库迁移或付费 API 的密钥。
- [ ] **步骤 2：运行任务配置测试。** 运行 `python -m pytest -q tests/platform/test_workflow_policy.py`。预期新增的“从 `main` 手动运行”断言失败。
- [ ] **步骤 3：修改工作流条件。** 允许从受信任的 `main` 手动触发采集，而不因此开启定时任务；只要运行分支是 `main` 就选择正式 GitHub Environment。定时任务仍必须同时满足“运行于 `main`”和“仓库变量已启用”。
- [ ] **步骤 4：运行工作流和采集回归测试。** 运行 `python -m pytest -q tests/platform/test_workflow_policy.py tests/platform/test_schedule.py tests/platform/test_site_runner.py tests/platform/test_runner.py`。预期全部通过。
- [ ] **步骤 5：提交。** 将任务 2 提交为 `ci: prepare free collectors for production schedule`。

### 任务 3：更新操作说明并通过开发环境验收

**涉及文件：**
- 修改：`docs/operations/platform.md`
- 仅在确需纠正原有说法时修改：`docs/verification/2026-10-21-unified-v1.md`；否则保留历史验证记录。

**接口约定：**
- 依据任务 1 的公开网站接口和任务 2 的正式定时任务配置。
- 产出一份当前可用的操作说明，清楚区分 Vercel 网页凭据与 GitHub Actions 采集凭据，并写明回退顺序。

- [ ] **步骤 1：更新操作说明。** 删除 Basic Auth 和受保护预览页的旧说明；写明公开设置的风险、UTC 与北京时间的准确采集时间、从 `main` 手动验证正式采集、`FREE_RADAR_ENABLED` 开关、单次 20 站点上限、环境名称、密钥用途和回退顺序。
- [ ] **步骤 2：检查是否还有过时的“必须登录”要求。** 运行 `rg -n "RADAR_WEB_USERNAME|RADAR_WEB_PASSWORD_SHA256|requires Basic Auth|Every route requires Basic Auth" radar tests api docs/operations .github pyproject.toml`。预期正在运行的代码、测试和当前操作说明中不再有这些要求；注明日期的旧设计或验证记录可作为历史保留。
- [ ] **步骤 3：运行完整的本地验收测试。** 运行 `python -m pytest -q tests/test_radar.py tests/platform tests/e2e`。预期全部通过，没有意外跳过的测试；Chrome 测试要验证免登录打开网页，以及从公开页面发出的同源设置修改。
- [ ] **步骤 4：运行隔离的开发 Neon 集成测试。** 使用已有、仅用于开发库的 `RADAR_TEST_*` 凭据运行 `python -m pytest -q tests/platform_integration`。预期全部通过；每个测试仅创建并清理自己的 `radar_test_*` 数据库 schema。
- [ ] **步骤 5：检查打包结果。** 运行 `python -m pytest -q tests/platform/test_package_merge.py`。预期源码导入、安装包导入、数据库迁移文件打包及 Vercel 入口都通过，且不要求网页登录凭据。
- [ ] **步骤 6：提交。** 将操作说明提交为 `docs: explain public automated radar operations`。

### 任务 4：为正式 Neon 数据库配置最小权限的服务端连接

**涉及文件：**
- 预计不改产品代码。
- 后续将经过脱敏的验证记录写入：`docs/verification/2026-10-22-public-auto-radar-release.md`。

**接口约定：**
- 为网页只读、竞品设置管理、采集写入和数据库迁移分别提供服务端连接地址；这些地址不能进入 Git、浏览器代码、截图或验证日志。
- 明确权限：reader 只能读取平台表；site-admin 只能对 `radar_sites` 执行读取、插入和更新；writer 可以修改采集数据表并读取、更新站点配置；migrator 负责平台数据库结构变更。

- [ ] **步骤 1：先检查现状。** 查询正式 Neon 分支中已执行的 `radar_schema_migrations`、所有 `radar_*` 表、四个数据库技术角色，以及六张旧 Trends 表的行数。只记录名称、行数和校验值，不记录连接地址。
- [ ] **步骤 2：仅创建缺少的技术角色。** 通过 SQL 使用 `LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS` 创建；不通过 Neon 控制台的角色创建操作，也不增加第五种角色。生成或更换密钥时，不在命令输出中显示密钥。
- [ ] **步骤 3：只执行尚未执行过的迁移。** 对正式库运行现有迁移程序。如果 `001_initial.sql` 和 `004_sitemap.sql` 已有记录，预计补上 `002_roles.sql`、`003_role_defaults.sql`、`005_site_roles.sql`。再运行一次应显示没有待执行迁移；一旦出现校验值不匹配，立即停止。
- [ ] **步骤 4：验证权限，不插入测试数据。** 使用 `has_schema_privilege`、`has_table_privilege`，并分别用四种角色连接执行 `SELECT 1`。确认 reader/site-admin 不能写入新词或页面事件，writer 不能改数据库结构，且四种角色都不继承 `neon_superuser`。
- [ ] **步骤 5：复查旧数据与测试残留。** 确认六张 Trends 表的行数不变，也不存在 `radar_test_*` schema。如有任何检查结果异常，在部署前停止，并用 Neon 的恢复能力处理；不直接删除表。

### 任务 5：通过现有 Vercel 项目发布公开网站

**涉及文件：**
- 创建或更新：`docs/verification/2026-10-22-public-auto-radar-release.md`

**接口约定：**
- 使用任务 4 准备的正式库 reader 和 site-admin 连接地址。
- 产出可免登录访问的正式网站地址；访客可以读取数据，并可通过同源请求修改竞品站点配置。

- [ ] **步骤 1：检查远端现状。** 更新 GitHub 远端信息；确认 `origin/main` 是当前开发分支的祖先，或以正常方式处理分支差异；确认当前分支干净且包含任务 1–3 的改动；检查现有 Vercel 项目的正式域名与访问保护状态。不强制推送。
- [ ] **步骤 2：配置 Vercel 服务端变量。** 在正式环境配置 `RADAR_READ_DATABASE_URL`、`RADAR_SITE_ADMIN_DATABASE_URL`，并将 `RADAR_WEB_ALLOWED_ORIGINS` 设置为准确的 HTTPS 正式站来源地址。移除旧的 `RADAR_WEB_USERNAME` 和 `RADAR_WEB_PASSWORD_SHA256`；Vercel 不配置 writer 或 migrator 凭据。
- [ ] **步骤 3：正常推送并发布。** 推送开发分支，通过正常快进或合并更新 `main`，让现有 Vercel 项目构建该次提交。
- [ ] **步骤 4：验证正式网站可免登录查看。** 使用干净的浏览器会话打开 `/`，切换总览、新词、竞品和设置页面，切换日期并打开研究卡；确认 `/api/overview`、`/api/daily-terms`、`/api/competitors` 和 `/api/settings/status` 不经登录或重定向即可返回 `200`。
- [ ] **步骤 5：验证真实设置写入，不留下虚假竞品。** 只有在尚未存在时才添加 `aiphotoeditor.com`，然后暂停、恢复这个真实站点；确认跨站请求和非法网址仍被拒绝。不创建无法在网页上删除的测试站点。
- [ ] **步骤 6：记录验收证据。** 在正式发布验证文档中记录 Vercel 部署编号与提交、公开网址、免登录检查结果、设置修改结果和可回退的部署版本；不记录密钥内容。

### 任务 6：启动采集并验证手动和定时运行

**涉及文件：**
- 修改：`docs/verification/2026-10-22-public-auto-radar-release.md`
- 仅在实际运行与操作说明不一致时修改：`docs/operations/platform.md`

**接口约定：**
- 使用 `free-radar-production` GitHub Environment，其中只配置 `RADAR_WRITE_DATABASE_URL`；使用任务 2 已发布到 `main` 的工作流。
- 产出真实的正式环境来源快照、真实竞品基线、已启用的后续定时任务，以及至少一次来源定时运行和一次竞品定时运行的记录。

- [ ] **步骤 1：建立正式 Actions 环境并配置写入密钥。** 此时仓库变量 `FREE_RADAR_ENABLED` 保持未设置或 `false`；不向采集任务提供 reader、site-admin、migrator、付费 API 或 Vercel 密钥。
- [ ] **步骤 2：在 `main` 手动触发 `sources`。** GitHub Actions 必须成功运行三个来源任务（GitHub、HF Models、HF Spaces）；正式 Neon 的 `radar_runs` 应有记录；设置页和新词接口应出现对应结果。只要运行结果为部分成功或不完整，就暂不启用定时任务。
- [ ] **步骤 3：在 `main` 手动触发 `sites`。** GitHub Actions 必须成功运行，且真实竞品要建立完整基线。首次快照应产生零条 URL 变化事件；同一天再次运行不能产生第二份实际生效的快照。
- [ ] **步骤 4：启用定时任务。** 只有步骤 2–3 通过后，才将仓库变量设为 `FREE_RADAR_ENABLED=true`；确认旧流程的 `RADAR_ENABLED` 仍未设置或为 `false`。
- [ ] **步骤 5：观察一次定时来源采集。** 等待下一个 UTC `00:00`、`08:00` 或 `16:00` 触发点，确认事件类型为 `schedule`、运行分支和提交对应 `main`、使用 `free-radar-production` 环境、Neon 中出现预期状态，且网页反映新结果。
- [ ] **步骤 6：观察一次定时竞品采集。** 等待下一个 UTC `01:30` 触发点，确认其正式环境身份；网址没有变化时不应生成事件，抓取失败或不完整时应保留旧基线。如果已启用站点超过 20 个，剩余站点应记录为未采集，而不是显示零变化。
- [ ] **步骤 7：完成最终验证和检查。** 再运行 `python -m pytest -q tests/test_radar.py tests/platform tests/e2e`，审查最终分支改动，并确认没有将密钥或本地环境文件纳入 Git。
- [ ] **步骤 8：提交并推送发布记录。** 确认记录不含凭据后，以 `docs: record public radar production verification` 提交经过脱敏的验证文档，并正常推送到 `main`。

## 何时回退

如果正式环境误写入其他 Neon 分支、采集程序把不完整结果推进为新基线、公开网站仍要求登录，或任一定时任务持续失败，应立即设置 `FREE_RADAR_ENABLED=false`，保持 `RADAR_ENABLED` 关闭，并将 Vercel 回退到上一个已验证可用的部署。保留 Neon 表和运行记录用于排查；回退时不删除或改写数据。
