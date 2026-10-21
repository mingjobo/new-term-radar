const content = document.querySelector("#content");
const topbar = document.querySelector("#topbar-content");
const sidebar = document.querySelector("#sidebar");
const menu = document.querySelector("#menu-toggle");
const state = {day: null, site: null, siteFilters: {}, eventFilters: {type: "all"}};
let renderToken = 0;

function node(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined && value !== null) element.textContent = String(value);
  return element;
}
function today() {
  return new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date());
}
function formatTime(value) {
  if (!value) return "尚无成功记录";
  const time = new Date(value);
  return Number.isNaN(time.valueOf()) ? String(value) :
    new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "short"}).format(time);
}
function safeHttpUrl(value) {
  try {
    const parsed = new URL(String(value));
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch (_) { return null; }
}
function evidenceLink(value, label = "查看出处 ↗") {
  const url = safeHttpUrl(value);
  if (!url) return node("span", "blocked-link", "链接已拦截");
  const link = node("a", "text-link", label);
  link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
  return link;
}
function statusLabel(value) {
  return ({ok: "正常", baseline: "首次建档", incomplete: "数据不完整", failed: "采集失败",
    stale: "更新逾期", paused: "已暂停", not_collected: "未采集", not_run: "未运行",
    partial: "部分成功", off: "未启用"})[value] || "未知状态";
}
async function api(path, options = {}) {
  const response = await fetch(new URL(path, window.location.origin), {
    credentials: "same-origin",
    headers: {Accept: "application/json", ...(options.body ? {"Content-Type": "application/json"} : {})},
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
  return payload;
}
function metric(label, value, key) {
  const card = node("article", "metric");
  card.append(node("span", "metric-label", label));
  const strong = node("strong", "metric-value", value === null || value === undefined ? "未采集" : value);
  strong.dataset.metric = key;
  card.append(strong);
  return card;
}
function empty(message, detail) {
  const box = node("section", "empty-state");
  box.append(node("strong", "", message));
  if (detail) box.append(node("p", "muted", detail));
  return box;
}
function failed(error, token) {
  if (token === renderToken) content.replaceChildren(empty("暂时无法读取", error.message));
}
function activeNav(view) {
  document.querySelectorAll("#primary-nav a").forEach((link) => {
    const active = link.dataset.nav === view;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  sidebar.classList.remove("open");
  menu.setAttribute("aria-expanded", "false");
  menu.setAttribute("aria-label", "打开菜单");
}
function boardTabs(active) {
  const tabs = node("div", "board-tabs"); tabs.id = "board-tabs";
  [["new", "新词"], ["competitors", "竞品"]].forEach(([key, label]) => {
    const button = node("button", key === active ? "tab active" : "tab", label);
    button.type = "button"; button.setAttribute("aria-pressed", String(key === active));
    button.addEventListener("click", () => {
      state.site = null;
      window.location.hash = key === "new" ? "#keywords/new" : "#keywords/competitors";
    });
    tabs.append(button);
  });
  topbar.replaceChildren(tabs);
}
function input(label, value = "", type = "text") {
  const wrap = node("label", "field");
  wrap.append(node("span", "", label));
  const field = node("input", "input");
  field.type = type; field.value = value || "";
  wrap.append(field);
  return [wrap, field];
}
function paging(page, total, size, change) {
  const bar = node("div", "paging");
  const back = node("button", "outline-button", "上一页");
  back.disabled = page <= 1; back.addEventListener("click", () => change(page - 1));
  const next = node("button", "outline-button", "下一页");
  next.disabled = page * size >= total; next.addEventListener("click", () => change(page + 1));
  bar.append(back, node("span", "muted", `第 ${page} 页 · 共 ${total} 条`), next);
  return bar;
}

async function overview(token) {
  activeNav("overview");
  const day = state.day || today();
  const date = node("input", "date-input"); date.id = "overview-date";
  date.type = "date"; date.value = day; date.max = today(); date.setAttribute("aria-label", "查看日期");
  date.addEventListener("change", () => { state.day = date.value || today(); route(); });
  const label = node("label", "date-control");
  label.append(node("span", "", "查看日期"), date); topbar.replaceChildren(label);
  content.replaceChildren(node("p", "loading", "正在读取当日总览…"));
  try {
    const data = await api(`/api/overview?date=${encodeURIComponent(day)}`);
    if (token !== renderToken) return;
    const grid = node("section", "overview-grid");
    grid.append(metric("新词", data.new_terms, "new_terms"), metric("线索", data.evidence, "evidence"),
      metric("有变化竞品", data.changed_sites, "changed_sites"), metric("新增 URL", data.added_urls, "added_urls"),
      metric("移出 Sitemap", data.removed_urls, "removed_urls"));
    content.replaceChildren(grid);
  } catch (error) { failed(error, token); }
}

function termRow(term) {
  const row = node("article", "term-row");
  const title = node("h3", "term-name", term.name);
  const meta = node("div", "term-meta");
  (term.sources || [term.source_instance]).filter(Boolean).forEach((source) => meta.append(node("span", "source-tag", source)));
  meta.append(node("time", "", formatTime(term.first_seen_at || term.discovered_at)));
  const actions = node("div", "row-actions");
  actions.append(evidenceLink(term.url));
  const detail = node("a", "text-link strong", "研究卡 →");
  detail.href = `/terms/${encodeURIComponent(term.id)}`;
  actions.append(detail); row.append(title, meta, actions);
  return row;
}
async function newTerms(token) {
  activeNav("keywords"); boardTabs("new");
  content.replaceChildren(node("p", "loading", "正在读取今日新词…"));
  try {
    const data = await api("/api/daily-terms?limit=50");
    if (token !== renderToken) return;
    const summary = data.summary || {};
    const strip = node("section", "daily-summary");
    const update = node("div", "summary-update");
    update.append(node("span", "muted-label", "最近成功更新"), node("strong", "", formatTime(summary.last_success_at)));
    strip.append(metric("今天新词", summary.new_terms, "today_new_terms"),
      metric("今日线索", summary.evidence, "today_evidence"), update);
    const list = node("section", "term-list");
    if (!data.items.length) {
      const message = summary.status === "failed" ? "今日来源采集失败" :
        summary.status === "not_collected" ? "今天尚未采集" : "今天暂无新词";
      const box = empty(message, summary.status === "failed" ? "请到设置查看采集原因。" : null);
      if (summary.status === "failed") {
        const link = node("a", "text-link", "查看设置 →"); link.href = "/#settings"; box.append(link);
      }
      list.append(box);
    } else data.items.forEach((item) => list.append(termRow(item)));
    content.replaceChildren(strip, list);
    if (data.next_cursor) {
      let cursor = data.next_cursor;
      const more = node("button", "outline-button more-button", "读取下一页");
      more.addEventListener("click", async () => {
        more.disabled = true;
        try {
          const next = await api(`/api/daily-terms?limit=50&cursor=${encodeURIComponent(cursor)}`);
          next.items.forEach((item) => list.append(termRow(item)));
          cursor = next.next_cursor;
          if (!cursor) more.remove(); else more.disabled = false;
        } catch (error) { more.textContent = error.message; more.disabled = false; }
      });
      content.append(more);
    }
  } catch (error) { failed(error, token); }
}

function siteRow(site) {
  const row = node("article", "site-row");
  const main = node("div", "site-main");
  const rangeStatus = site.range_status || "not_collected";
  const displayStatus = site.status === "paused" ? "paused" :
    rangeStatus === "ok" ? site.status : rangeStatus;
  main.append(node("strong", "site-name", site.name),
    node("span", `status-text status-${displayStatus}`, statusLabel(displayStatus)),
    node("small", "muted", `最近成功 ${formatTime(site.last_success_at)}`));
  const counts = node("div", "site-counts");
  counts.append(node("span", "", `新增 ${rangeStatus === "ok" ? site.added_urls ?? 0 : "—"}`),
    node("span", "", `移出 ${rangeStatus === "ok" ? site.removed_urls ?? 0 : "—"}`));
  const button = node("button", "outline-button", "查看页面");
  button.addEventListener("click", () => { state.site = site.id; state.eventFilters = {type: "all"}; siteDetail(site.id, 1); });
  row.append(main, counts, button); return row;
}
async function competitors(token, page = 1) {
  activeNav("keywords"); boardTabs("competitors");
  content.replaceChildren(node("p", "loading", "正在读取竞品站点…"));
  const filters = state.siteFilters;
  const params = new URLSearchParams({page: String(page), limit: "20"});
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  try {
    const data = await api(`/api/competitors?${params}`);
    if (token !== renderToken) return;
    const controls = node("div", "filter-bar");
    const [searchWrap, search] = input("站点名称", filters.q); search.placeholder = "搜索站点";
    const changedWrap = node("label", "check-field");
    const changed = node("input"); changed.type = "checkbox"; changed.checked = filters.changed === "1";
    changedWrap.append(changed, node("span", "", "只看有变化"));
    const status = node("select", "input"); status.setAttribute("aria-label", "站点状态");
    [["", "全部状态"], ["baseline", "首次建档"], ["ok", "正常"], ["incomplete", "数据不完整"],
      ["failed", "采集失败"], ["not_collected", "未采集"], ["stale", "更新逾期"], ["paused", "已暂停"]]
      .forEach(([value, label]) => { const option = node("option", "", label); option.value = value; status.append(option); });
    status.value = filters.status || "";
    const [fromWrap, from] = input("从", filters.from, "date");
    const [toWrap, to] = input("到", filters.to, "date");
    const apply = node("button", "solid-button", "筛选");
    apply.addEventListener("click", () => {
      state.siteFilters = {q: search.value.trim(), changed: changed.checked ? "1" : "",
        status: status.value, from: from.value, to: to.value};
      route();
    });
    controls.append(searchWrap, changedWrap, status, fromWrap, toWrap, apply);
    const summary = node("section", "compact-summary");
    const complete = data.summary.range_complete === true;
    summary.append(metric("监测站点", data.summary.sites, "sites"),
      metric("新增 URL", complete ? data.summary.added_urls : null, "added_urls"),
      metric("移出 Sitemap", complete ? data.summary.removed_urls : null, "removed_urls"),
      metric("异常站点", data.summary.abnormal_sites, "abnormal_sites"));
    const list = node("section", "site-list");
    if (!data.items.length) list.append(empty("没有匹配的站点"));
    data.items.forEach((site) => list.append(siteRow(site)));
    content.replaceChildren(controls, summary, list,
      paging(page, data.total, data.page_size || 20, (next) => competitors(++renderToken, next)));
  } catch (error) { failed(error, token); }
}
function eventRow(event) {
  const row = node("article", "event-row");
  row.append(node("span", event.event_type === "added" ? "event-type added" : "event-type removed",
    event.event_type === "added" ? "新增" : "移出站点地图"));
  const main = node("div", "event-main");
  main.append(node("strong", "event-path", event.path || "/"), node("small", "event-url", event.url));
  row.append(main, node("time", "event-time", formatTime(event.discovered_at)),
    evidenceLink(event.url, "打开原始页面"));
  return row;
}
async function siteDetail(siteId, page = 1) {
  const token = ++renderToken;
  activeNav("keywords"); boardTabs("competitors");
  content.replaceChildren(node("p", "loading", "正在读取页面清单…"));
  const filters = state.eventFilters;
  const params = new URLSearchParams({page: String(page), limit: "50"});
  Object.entries(filters).forEach(([key, value]) => { if (value && !(key === "type" && value === "all")) params.set(key, value); });
  try {
    const data = await api(`/api/competitors/${encodeURIComponent(siteId)}/events?${params}`);
    if (token !== renderToken) return;
    const heading = node("div", "detail-heading");
    const back = node("button", "text-button", "← 返回站点");
    back.addEventListener("click", () => { state.site = null; route(); });
    heading.append(back, node("h2", "", data.site.name));
    const controls = node("div", "filter-bar");
    const type = node("select", "input"); type.setAttribute("aria-label", "页面变化类型");
    [["all", "全部"], ["added", "新增"], ["removed", "移出站点地图"]]
      .forEach(([value, label]) => { const option = node("option", "", label); option.value = value; type.append(option); });
    type.value = filters.type || "all";
    const [searchWrap, search] = input("URL 路径", filters.q); search.placeholder = "搜索路径";
    const [fromWrap, from] = input("从", filters.from, "date");
    const [toWrap, to] = input("到", filters.to, "date");
    const apply = node("button", "solid-button", "筛选");
    apply.addEventListener("click", () => {
      state.eventFilters = {type: type.value, q: search.value.trim(), from: from.value, to: to.value};
      siteDetail(siteId);
    });
    controls.append(type, searchWrap, fromWrap, toWrap, apply);
    const list = node("section", "event-list");
    if (!data.items.length) {
      const filtered = Boolean(filters.q || filters.from || filters.to || (filters.type && filters.type !== "all"));
      let message = "当天没有页面增减";
      let detail = "这一天的站点地图中没有发现新增或移出的 URL。";
      if (data.site.status === "paused") {
        message = "站点监控已暂停";
        detail = "历史记录仍保留，恢复后才会继续采集。";
      } else if (data.site.range_status === "not_collected") {
        message = filtered ? "所选时段尚未采集站点地图" : "今天尚未采集站点地图";
        detail = "采集完成后才会判断该时段是否有页面增减。";
      } else if (data.site.range_status === "failed" || data.site.range_status === "incomplete") {
        message = data.site.range_status === "incomplete" ? "本次采集不完整" : "本次采集失败";
        detail = data.site.last_run_reason || "旧页面清单已保留，这次不会推断页面移出。";
      } else if (filtered) {
        message = "没有匹配的页面变化";
        detail = "可调整筛选条件再查看。";
      } else if (data.site.status === "not_collected") {
        message = "尚未采集站点地图";
        detail = "首次完整采集后才会建立基线。";
      } else if (data.site.status === "baseline") {
        message = "首次建档尚无页面增减";
        detail = "首次完整采集只记录页面清单，不把已有页面算作新增。";
      } else if (data.site.status === "stale") {
        message = "站点地图尚未更新";
        detail = "最近一次完整采集已超过两天。";
      }
      list.append(empty(message, detail));
    }
    data.items.forEach((item) => list.append(eventRow(item)));
    content.replaceChildren(heading, controls, list,
      paging(page, data.total, data.page_size || 50, (next) => siteDetail(siteId, next)));
  } catch (error) { failed(error, token); }
}

function sourceRow(source) {
  const row = node("article", "settings-source-row");
  const name = node("div");
  name.append(node("strong", "", source.source_instance),
    node("span", `status-text status-${source.status}`, statusLabel(source.status)));
  row.append(name, node("span", "", `${source.snapshot_items ?? 0} 项基线`),
    node("span", "muted", `上次成功 ${formatTime(source.last_success_at)}`),
    node("span", "muted", `本次新增 ${source.new_terms_last_run ?? "—"}`));
  return row;
}
function settingsSiteRow(site) {
  const row = node("article", "settings-site-row");
  const info = node("div", "settings-site-info");
  info.append(node("strong", "", site.name),
    node("span", `status-text status-${site.status}`, statusLabel(site.status)),
    node("small", "muted", site.host),
    node("small", "muted", `${site.url_count ?? "—"} 项基线 · 最近成功 ${formatTime(site.last_success_at)}`));
  if (site.last_run_reason) info.append(node("small", "warning", site.last_run_reason));
  const actions = node("div", "row-actions");
  const edit = node("button", "text-button", "编辑");
  edit.addEventListener("click", () => {
    if (row.querySelector(".edit-form")) return;
    const form = node("form", "edit-form");
    const [nameWrap, name] = input("站点名称", site.name);
    const [mapWrap, sitemap] = input("Sitemap 地址（可选）", site.sitemap_url || "");
    const save = node("button", "solid-button", "保存"); save.type = "submit";
    const cancel = node("button", "text-button", "取消"); cancel.type = "button";
    cancel.addEventListener("click", () => form.remove());
    const message = node("p", "form-message");
    form.append(nameWrap, mapWrap, save, cancel, message);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api(`/api/settings/sites/${encodeURIComponent(site.id)}`,
          {method: "PATCH", body: JSON.stringify({name: name.value, sitemap_url: sitemap.value || null, enabled: site.enabled})});
        settings(++renderToken);
      } catch (error) { message.textContent = error.message; }
    });
    row.append(form);
  });
  const toggle = node("button", "outline-button", site.enabled ? "暂停" : "恢复");
  toggle.addEventListener("click", async () => {
    toggle.disabled = true;
    try {
      await api(`/api/settings/sites/${encodeURIComponent(site.id)}`,
        {method: "PATCH", body: JSON.stringify({name: site.name, sitemap_url: site.sitemap_url, enabled: !site.enabled})});
      settings(++renderToken);
    } catch (error) {
      toggle.disabled = false; actions.append(node("span", "warning", error.message));
    }
  });
  actions.append(edit, toggle); row.append(info, actions);
  return row;
}
async function settings(token) {
  activeNav("settings"); topbar.replaceChildren(node("span", "topbar-title", "设置"));
  content.replaceChildren(node("p", "loading", "正在读取设置…"));
  try {
    const data = await api("/api/settings/status");
    if (token !== renderToken) return;
    const sources = node("section", "settings-section");
    sources.append(node("h2", "section-title", "来源状态"));
    data.sources.forEach((source) => sources.append(sourceRow(source)));
    const sites = node("section", "settings-section");
    sites.append(node("h2", "section-title", "竞品站点"));
    const form = node("form", "add-site-form");
    const [nameWrap, name] = input("站点名称"); name.id = "site-name"; name.required = true;
    const [homeWrap, homepage] = input("主页地址", "", "url"); homepage.id = "site-homepage"; homepage.required = true;
    const [mapWrap, sitemap] = input("Sitemap 地址（可选）", "", "url"); sitemap.id = "site-sitemap";
    const add = node("button", "solid-button", "添加站点"); add.type = "submit";
    const message = node("p", "form-message");
    form.append(nameWrap, homeWrap, mapWrap, add, message);
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); add.disabled = true;
      try {
        await api("/api/settings/sites", {method: "POST",
          body: JSON.stringify({name: name.value, homepage_url: homepage.value, sitemap_url: sitemap.value || null})});
        settings(++renderToken);
      } catch (error) { message.textContent = error.message; add.disabled = false; }
    });
    sites.append(form);
    const list = node("div", "settings-site-list");
    if (!data.sites.length) list.append(empty("尚未添加竞品站点"));
    data.sites.forEach((site) => list.append(settingsSiteRow(site)));
    sites.append(list);
    content.replaceChildren(sources, sites);
  } catch (error) { failed(error, token); }
}

function evidenceCard(item) {
  const card = node("article", "evidence-card");
  card.append(node("span", "source-tag", item.source_instance),
    node("time", "muted", formatTime(item.observed_at)),
    node("p", "evidence-quote", item.excerpt || "该来源没有提供文字摘要。"));
  const metrics = node("dl", "evidence-metrics");
  Object.entries(item.metrics || {}).slice(0, 6).forEach(([key, value]) => {
    metrics.append(node("dt", "", key.replaceAll("_", " ")),
      node("dd", "", typeof value === "object" ? JSON.stringify(value) : value));
  });
  card.append(metrics, evidenceLink(item.url, "打开原始证据 ↗"));
  return card;
}
async function detail(termId, token) {
  activeNav("keywords"); topbar.replaceChildren(node("span", "topbar-title", "研究卡"));
  content.replaceChildren(node("p", "loading", "正在读取研究卡…"));
  try {
    const term = await api(`/api/terms/${encodeURIComponent(termId)}`);
    if (token !== renderToken) return;
    const back = node("a", "text-link back-link", "← 返回新词"); back.href = "/#keywords/new";
    const title = node("h1", "detail-title", term.name);
    const meta = node("p", "muted", `首次发现 ${formatTime(term.first_seen_at)} · 最近观测 ${formatTime(term.last_seen_at)}`);
    const evidence = node("section", "evidence-list");
    term.evidence.forEach((item) => evidence.append(evidenceCard(item)));
    content.replaceChildren(back, title, meta, evidence);
  } catch (error) { failed(error, token); }
}
function route() {
  const token = ++renderToken;
  const found = window.location.pathname.match(/^\/terms\/([^/]+)$/);
  if (found) return detail(found[1], token);
  if (window.location.hash === "#settings") return settings(token);
  if (window.location.hash.startsWith("#keywords")) {
    if (window.location.hash === "#keywords/competitors") {
      return state.site ? siteDetail(state.site) : competitors(token);
    }
    return newTerms(token);
  }
  return overview(token);
}
menu.addEventListener("click", () => {
  const open = sidebar.classList.toggle("open");
  menu.setAttribute("aria-expanded", String(open));
  menu.setAttribute("aria-label", open ? "关闭菜单" : "打开菜单");
});
window.addEventListener("hashchange", () => { state.site = null; route(); });
route();
