# Hugging Face 采集修复与上游 0.5.1 同步

日期：2026-10-26。基准：自有 `origin/main` 的 `b74c291`；上游 `upstream/main` 的 `4fd9a0d`。在隔离工作区执行，不覆盖原有工作区。

## 目标与边界

- 修复正式采集器在 GitHub Actions 上选择 Hugging Face IPv6 地址后报 `ENETUNREACH` 的问题。
- 合入上游 0.5.1 的新卖家信号、命令行和安装改进，保留本 fork 的免费 Neon/Vercel 工作台与定时采集。
- 上游付费信号仍只在原有 `daily`/`history` 命令中按其配置使用；免费 `collect` 工作流不调用这些入口，不增加生产密钥或数据库迁移。
- 不把一次本地测试当成线上修复；合入后须检查真实定时采集或在已授权环境做等价的端到端验证。

## 证据与现状

- 2026-10-26 GitHub Actions 的只读诊断运行 `40280777964`：DNS 同时返回 IPv6/IPv4，现有 pinned 客户端两类 HF 请求均报 `OSError(101, Network is unreachable)`；同机 `urllib` 请求两类接口均返回 200。
- 本机同一接口 pinned/urllib 均成功，说明问题依赖 GitHub 运行机的网络能力。
- 上游相对共同祖先 `e2d33c3` 有 16 个提交；重叠修改的文件为发布工作流、两份 README、`pyproject.toml`、`radar/__main__.py`。
- 改动前基线：`python3 -m pytest -q tests/test_radar.py tests/platform tests/e2e` 为 213 passed。

## 任务 1：地址选择回归与修复

- [ ] 在 `tests/platform/test_http.py` 增加混合 IPv6/IPv4 DNS 的测试：两者都须经过公网地址校验，传给 transport 的目标必须是 IPv4；纯 IPv6 仍可使用；私网地址仍须拒绝。
- [ ] 先运行新测试确认失败，再仅在 `radar/platform/http.py` 调整地址选择，重新运行 HTTP 与采集测试。
- [ ] 移除临时 GitHub 网络诊断 job；保留 Actions 运行链接和上面的结论。

## 任务 2：合入上游

- [ ] 将 `upstream/main` 合入本分支。冲突中保留本 fork 的平台依赖、Vercel 入口、package 列表和静态资源；加入上游的 0.5.1 版本、打包示例配置、新卖家命令；README 保留 fork 说明并吸收上游更新。
- [ ] 核对 `radar/__main__.py` 仍有平台命令，`free-platform.yml` 仍只运行免费 `collect`，上游发布工作流仍不会由本 fork 自动发布包。
- [ ] 检查新增卖家功能的默认行为、价格提示及原有命令兼容性；只做必要的整合修正。

## 任务 3：验收与整合

- [ ] 运行完整测试、打包测试和安装包入口检查；检查网页 API、来源适配器和站点比较的原有测试。
- [ ] 对照基准与上游差异审查完整改动，检查未提交和未跟踪文件；将结果记入验证记录。
- [ ] 经项目约定的 PR/审查和检查通过后合入 `main`，确认发布版本，再读取正式新词来源状态和下一轮 Actions 结果。

## 审查重点

- DNS 同时有私网和公网地址时不能因偏向 IPv4 而放过私网地址。
- 没有 IPv4 的合法站点不能被新策略误拒绝。
- 安装包须同时包含 `platform` 模块及上游 `config.example.json`。
- 免费工作流不得新增 AIsa、GoAnyAPI、DataForSEO 或卖家历史采集调用。
- 上游 CLI 和 README 的新增内容不能误写成当前免费网页已上线的功能。
