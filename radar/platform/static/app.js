const app = document.querySelector("#app");

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function safeHttpUrl(value) {
  try {
    const parsed = new URL(value, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch (_) {
    return null;
  }
}

function evidenceLink(value, label = "查看出处 ↗") {
  const safe = safeHttpUrl(value);
  if (!safe) return node("span", "unsafe-link", "链接已拦截");
  const link = node("a", "evidence-link", label);
  link.href = safe;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function formatTime(value) {
  if (!value) return "尚无成功记录";
  const time = new Date(value);
  return Number.isNaN(time.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai"}).format(time);
}

async function api(path) {
  const response = await fetch(new URL(path, window.location.origin), {credentials: "same-origin", headers: {Accept: "application/json"}});
  if (!response.ok) throw new Error(`读取失败（${response.status}）`);
  return response.json();
}

function metric(label, value, note) {
  const card = node("article", "metric-card");
  card.append(node("p", "metric-label", label), node("strong", "metric-value", value), node("small", "metric-note", note));
  return card;
}

function statusLabel(status) {
  const labels = {
    ok: "成功",
    baseline: "基线已建立",
    incomplete: "数据不完整",
    failed: "失败",
    stale: "已过期",
    off: "未启用",
    not_run: "尚未运行",
  };
  return labels[status] || status || "未知";
}

function sourceStrip(sources) {
  const section = node("section", "source-strip");
  section.append(node("p", "eyebrow", "SOURCE PULSE / 来源状态"));
  const grid = node("div", "source-grid");
  sources.forEach((source) => {
    const card = node("article", `source-card status-${source.status}`);
    const top = node("div", "source-top");
    top.append(node("strong", "source-name", source.source_instance), node("span", "status-chip", statusLabel(source.status)));
    card.append(top, node("p", "source-count", `${source.snapshot_items ?? 0} 项基线`), node("small", "source-time", formatTime(source.last_success_at)));
    grid.append(card);
  });
  section.append(grid);
  return section;
}

function termRow(term) {
  const row = node("article", "term-row");
  const main = node("div", "term-main");
  main.append(node("span", "term-kind", term.kind), node("h3", "term-name", term.name));
  const context = node("p", "term-context", term.excerpt || "暂无摘要；保留名称和原始证据。");
  const meta = node("div", "term-meta");
  meta.append(node("span", "source-tag", term.source_instance || "未知来源"), node("time", "", formatTime(term.observed_at || term.first_seen_at)));
  if (term.metrics?.stars !== undefined) meta.append(node("span", "metric-inline", `★ ${Number(term.metrics.stars).toLocaleString()}`));
  if (term.metrics?.rank !== undefined) meta.append(node("span", "metric-inline", `#${term.metrics.rank}`));
  const actions = node("div", "term-actions");
  actions.append(evidenceLink(term.url));
  const detail = node("a", "detail-link", "研究卡 →");
  detail.href = `/terms/${encodeURIComponent(term.id)}`;
  actions.append(detail);
  row.append(main, context, meta, actions);
  return row;
}

function termsSection(payload) {
  const section = node("section", "terms-section");
  const heading = node("div", "section-heading");
  const title = node("div");
  title.append(node("p", "eyebrow", "INBOX / 新词收件箱"), node("h2", "", "值得继续观察的名字"));
  const count = node("span", "edition-number", `${payload.items.length} 条`);
  heading.append(title, count);
  const list = node("div", "term-list");
  if (!payload.items.length) list.append(node("p", "empty", "当前筛选没有结果。"));
  payload.items.forEach((term) => list.append(termRow(term)));
  section.append(heading, list);
  if (payload.next_cursor) {
    const more = node("button", "load-more", "读取下一页");
    more.addEventListener("click", () => loadMore(payload.next_cursor, list, more));
    section.append(more);
  }
  return section;
}

async function loadMore(cursor, list, button) {
  button.disabled = true;
  button.textContent = "读取中…";
  try {
    const payload = await api(`/api/terms?limit=50&sort=newest&cursor=${encodeURIComponent(cursor)}`);
    payload.items.forEach((term) => list.append(termRow(term)));
    if (payload.next_cursor) {
      button.disabled = false;
      button.textContent = "读取下一页";
      button.onclick = () => loadMore(payload.next_cursor, list, button);
    } else {
      button.remove();
    }
  } catch (error) {
    button.disabled = false;
    button.textContent = error.message;
  }
}

function renderHome(overview, terms, sources) {
  const fragment = document.createDocumentFragment();
  const hero = node("section", "hero");
  const copy = node("div", "hero-copy");
  copy.append(node("p", "eyebrow", "DAILY SIGNAL / 今日概览"), node("h1", "", "名字先出现，需求随后留下证据。"), node("p", "dek", "免费来源自动采集。这里只陈列真实观测、采集时间和可回看的出处，不制造搜索量。"));
  const metrics = node("div", "metric-grid");
  metrics.append(
    metric("今日新名称", overview.new_terms_today, "北京时间自然日"),
    metric("今日证据", overview.evidence_today, "已入库观测"),
    metric("来源在线", overview.source_count, `${overview.failed_runs_today || 0} 次失败`),
  );
  hero.append(copy, metrics);
  fragment.append(hero, sourceStrip(sources), termsSection(terms));
  app.replaceChildren(fragment);
  document.querySelector("#footer-updated").textContent = `LAST RUN ${formatTime(overview.latest_run_at)}`;
}

function evidenceCard(item) {
  const card = node("article", "evidence-card");
  const head = node("div", "evidence-head");
  head.append(node("span", "source-tag", item.source_instance), node("time", "", formatTime(item.observed_at)));
  card.append(head, node("p", "evidence-quote", item.excerpt || "该来源没有提供文字摘要。"));
  const metrics = node("dl", "evidence-metrics");
  Object.entries(item.metrics || {}).slice(0, 6).forEach(([key, value]) => {
    metrics.append(node("dt", "", key.replaceAll("_", " ")), node("dd", "", typeof value === "object" ? JSON.stringify(value) : value));
  });
  card.append(metrics, evidenceLink(item.url, "打开原始证据 ↗"));
  return card;
}

function renderDetail(term) {
  const back = node("a", "back-link", "← 返回新词收件箱");
  back.href = "/";
  const hero = node("section", "detail-hero");
  hero.append(node("p", "eyebrow", `${term.kind} / ${term.language}`), node("h1", "", term.name), node("p", "canonical", term.canonical_key), node("p", "dek", `首次发现 ${formatTime(term.first_seen_at)} · 最近观测 ${formatTime(term.last_seen_at)}`));
  const evidence = node("section", "evidence-section");
  evidence.append(node("p", "eyebrow", "EVIDENCE FILE / 证据档案"), node("h2", "", `${term.evidence.length} 条可追溯观测`));
  const list = node("div", "evidence-list");
  term.evidence.forEach((item) => list.append(evidenceCard(item)));
  evidence.append(list);
  app.replaceChildren(back, hero, evidence);
  document.querySelector("#footer-updated").textContent = `TERM UPDATED ${formatTime(term.last_seen_at)}`;
}

function renderError(error) {
  const section = node("section", "error-state");
  section.append(node("p", "eyebrow", "DATABASE NOTE"), node("h1", "", "研究台暂时无法读取。"), node("p", "dek", error.message));
  app.replaceChildren(section);
}

async function boot() {
  document.querySelector("#edition-date").textContent = new Intl.DateTimeFormat("zh-CN", {dateStyle: "full", timeZone: "Asia/Shanghai"}).format(new Date());
  try {
    const detailMatch = window.location.pathname.match(/^\/terms\/([^/]+)$/);
    if (detailMatch) {
      renderDetail(await api(`/api/terms/${encodeURIComponent(detailMatch[1])}`));
      return;
    }
    const [overview, terms, sources] = await Promise.all([
      api("/api/overview"),
      api("/api/terms?limit=50&sort=newest"),
      api("/api/sources"),
    ]);
    renderHome(overview, terms, sources.items);
  } catch (error) {
    renderError(error);
  }
}

boot();
