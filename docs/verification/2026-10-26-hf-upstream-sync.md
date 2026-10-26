# Hugging Face 采集故障与上游同步验收 — 2026-10-26

## 版本与环境

- 自有基准：`origin/main` / `b74c291`；上游：`upstream/main` / `4fd9a0d`（0.5.1）；隔离工作区分支：`codex/radar-upstream-hf`。
- 变更范围：免费 HTTP 客户端选择地址、上游 0.5.1 代码与文档、合并冲突中的 README/打包配置。没有数据库迁移或正式环境变量变更。

## 故障根因

- 正式来源任务在 2026-10-26 的 [Actions 运行 40264362894](https://github.com/mingjobo/new-term-radar/actions/runs/40264362894) 中，GitHub 成功，Hugging Face Models/Spaces 均报 `HttpError: HTTP request failed: OSError`。
- [修复前同机只读诊断 40280777964](https://github.com/mingjobo/new-term-radar/actions/runs/40280777964)：`huggingface.co` 同时解析到 IPv6 和 IPv4。旧客户端按地址字符串排序并选首个 IPv6；GitHub 运行机对该地址报 `OSError(101, Network is unreachable)`。同机 `urllib` 两个 API 均返回 200，因此并非凭据、接口返回格式或 Hugging Face 整体不可用。
- 旧测试只检查单个 IPv4 地址，没有双栈解析情形。新增测试先在旧实现上失败，实际拿到 IPv6；修复后在全部解析结果继续做公网校验，再优先选 IPv4。仅有 IPv6 时仍使用 IPv6，混有私网地址仍拒绝。
- [修复后同机只读诊断 40281003518](https://github.com/mingjobo/new-term-radar/actions/runs/40281003518)：两个 API 的 pinned 客户端各连续两次返回 200；诊断没有读取数据库或写入生产数据。临时诊断 job 已从最终工作流文件移除。

## 上游整合

- 纳入 0.5.1：新增卖家收款链接信号和历史命令、无配置文件时的示例配置、打包示例文件、MCP/Skill 的付费提示与外部内容边界、文档与图示更新。
- 合并冲突：保留本 fork 的 Neon/Vercel 运行依赖、平台包和静态资源；同时加入上游示例配置。README 保留本 fork 线上工作台说明，并标明下文的付费 CLI 功能不在免费定时任务中。`radar/__main__.py` 同时保留平台命令与上游新命令。
- 免费 Actions 工作流仍只执行 `python -m radar collect --kind sources|sites`；没有加入付费 API 密钥或卖家采集调用。
- 独立代码审查发现上游 `page_words` 原先直接用 `urllib` 访问外部提供的域名，存在跨域/内网重定向风险；现在复用平台 HTTP 客户端的公网地址、固定 IP、允许域名与重定向校验，允许同一站的 `www` 跳转，并保留最多读取页面前段的行为。
- 审查也发现 `--max-usd 0` 被当成默认预算，且小于单页预估费用时仍会请求。现在显式零预算不会付费，剩余额度不足观测单页费用约 $0.06 时不会继续；服务方事后报价，因此文档明确预算只是估算上限。两份 README 补充卖家费用和跳过选项。

## 已执行的检查

- 修复前隔离工作区基线：`python3 -m pytest -q tests/test_radar.py tests/platform tests/e2e` → **213 passed**。
- 双栈回归测试先得到 **1 failed, 2 passed**，失败点为选择 IPv6；修复后 HTTP、Hugging Face、Sitemap、runner 相关测试 **35 passed**。
- 上游合并后本地 `python3 -m pytest -q tests` → **231 passed, 36 skipped**；审查修正后同命令 → **235 passed, 36 skipped**。跳过项需要隔离 Neon 测试凭据；这次没有把本地通过说成远端数据库集成通过。
- 卖家网页读取与预算测试先在旧实现上失败，再修复后通过；包括 gzip 截断、内网重定向、零预算、小额预算和限制下载大小。
- `uv build --wheel` 成功；wheel 内确认包含示例配置、平台 HTTP、网页模板、数据库迁移、卖家代码。`git diff --check` 与 `git diff --cached --check` 均通过。
- 按 Yao 的技能包检查脚本评估三份上游 Skill：它们沿用上游单文件结构，缺少 `agents/interface.yaml`，且超过该脚本的 Production 初始加载预算。这是技能包发布检查的未通过项；本次只同步仓库文件，不将这些 Skill 单独安装或发布为经过 Yao 验收的技能包。

## 尚需确认

- PR 检查、正式 `main` 更新与 Vercel 发布后的版本核对。
- 修复代码进入正式运行后，下一次 `sources` 任务应在 GitHub Actions 和网页状态中三源成功；只读诊断的 200 不能代替完整入库验收。
