const controlToken = document.querySelector('meta[name="local-control-token"]').content;
const byId = (id) => document.getElementById(id);
const state = {
  status: null,
  kbs: [],
  cloudKbs: [],
  tasks: [],
  selectedKbs: new Set(),
  currentTaskId: null,
  pollingTaskId: null,
  sources: [],
  trace: [],
};
let toastTimer;

async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if ((options.method || "GET") !== "GET") headers.set("X-Local-Control-Token", controlToken);
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail?.message || "请求失败，请稍后重试");
  return payload;
}

async function requestText(path) {
  const response = await fetch(path, { headers: { Accept: "text/markdown" } });
  if (!response.ok) throw new Error("研究报告读取失败");
  return response.text();
}

function notify(message, kind = "success") {
  const toast = byId("alert");
  clearTimeout(toastTimer);
  toast.hidden = false;
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
}

function setBusy(button, busy, label) {
  if (!button.dataset.content) button.dataset.content = button.innerHTML;
  button.disabled = busy;
  if (busy) button.textContent = label;
  else button.innerHTML = button.dataset.content;
}

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value == null ? "" : String(value);
  return span.innerHTML;
}

function formatDate(value, fallback = "—") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function kbName(id) {
  if (!id) return "外部来源";
  return state.kbs.find((kb) => kb.id === id)?.name || "未知知识库";
}

function statusLabel(status) {
  return { queued: "等待中", running: "运行中", completed: "已完成", failed: "失败" }[status] || status;
}

function phaseLabel(phase) {
  return {
    queued: "等待执行", starting: "正在启动", planning: "正在规划研究问题",
    retrieval: "正在检索知识库", quick_research: "正在补充 Web Research",
    deep_research: "正在执行 Deep Research", sufficiency: "正在检查证据充分性",
    synthesis: "正在撰写报告", finalizing: "正在保存研究结果",
    completed: "研究已完成", failed: "研究未完成",
  }[phase] || "正在研究";
}

function sourceTypeLabel(sourceType) {
  return {
    local_import: "Local KB", web_upload: "Cloud KB", external_web: "Web Research",
  }[sourceType] || sourceType || "未知来源";
}

function elapsedLabel(startedAt) {
  if (!startedAt) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `已运行 ${seconds} 秒`;
  return `已运行 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

function taskKbTags(task) {
  const ids = task.knowledge_base_ids || [];
  return ids.length
    ? ids.map((id) => `<span class="kb-tag">${escapeHtml(kbName(id))}</span>`).join("")
    : '<span class="kb-tag">本地知识库</span>';
}

function taskRows(tasks) {
  return tasks.map((task) => `
    <tr class="task-row" data-task-id="${escapeHtml(task.id)}">
      <td><div class="task-title"><svg><use href="#i-file"></use></svg><span>${escapeHtml(task.query)}</span></div></td>
      <td><div class="kb-tags">${taskKbTags(task)}</div></td>
      <td><span class="status-badge ${escapeHtml(task.status)}">${escapeHtml(statusLabel(task.status))}</span></td>
      <td>${escapeHtml(formatDate(task.completed_at || task.started_at || task.created_at))}</td>
    </tr>`).join("");
}

function bindTaskRows(container) {
  container.querySelectorAll("[data-task-id]").forEach((row) => row.addEventListener("click", () => {
    showResult(row.dataset.taskId);
  }));
}

function renderTasks() {
  const recent = state.tasks.slice(0, 5);
  byId("recent-tasks").innerHTML = taskRows(recent);
  byId("history-tasks").innerHTML = taskRows(state.tasks);
  byId("recent-empty").hidden = recent.length > 0;
  byId("history-empty").hidden = state.tasks.length > 0;
  bindTaskRows(byId("recent-tasks"));
  bindTaskRows(byId("history-tasks"));
}

function renderKbChips() {
  const target = byId("composer-kbs");
  if (!state.kbs.length) {
    target.innerHTML = '<span class="kb-empty">暂无本地知识库，<button type="button" data-route="knowledge">先创建一个</button></span>';
    bindRouteButtons(target);
    return;
  }
  if (![...state.selectedKbs].some((id) => state.kbs.some((kb) => kb.id === id))) {
    state.selectedKbs = new Set([state.kbs[0].id]);
  }
  target.innerHTML = state.kbs.map((kb) => `<button type="button" class="kb-chip ${state.selectedKbs.has(kb.id) ? "selected" : ""}" data-kb-id="${escapeHtml(kb.id)}" aria-pressed="${state.selectedKbs.has(kb.id)}">${escapeHtml(kb.name)}</button>`).join("");
  target.querySelectorAll("[data-kb-id]").forEach((button) => button.addEventListener("click", () => {
    if (state.selectedKbs.has(button.dataset.kbId)) state.selectedKbs.delete(button.dataset.kbId);
    else state.selectedKbs.add(button.dataset.kbId);
    renderKbChips();
  }));
}

function replaceOptions(select, items, emptyLabel) {
  const selected = select.value;
  select.replaceChildren(new Option(emptyLabel, ""));
  items.forEach((item) => select.add(new Option(item.name, item.id)));
  if (items.some((item) => item.id === selected)) select.value = selected;
}

function renderKbOptions() {
  replaceOptions(byId("file-local-kb"), state.kbs, state.kbs.length ? "选择本地知识库" : "暂无本地知识库");
  replaceOptions(byId("transfer-local-kb"), state.kbs, state.kbs.length ? "选择本地知识库" : "暂无本地知识库");
  replaceOptions(byId("transfer-cloud-kb"), state.cloudKbs,
    state.status?.cloud_token_configured ? "选择云端知识库" : "Cloud 未连接");
  updateTransferButtons();
}

async function loadStatus() {
  state.status = await request("/api/local/status");
  byId("allowed-root").textContent = state.status.allowed_root;
  byId("local-database").textContent = state.status.local_database;
  byId("research-provider").textContent = state.status.providers?.research?.configured ? "已配置" : "未配置";
  byId("web-search-provider").textContent = state.status.providers?.web_search?.configured ? "已配置" : "未配置";
  const providerState = state.status.providers || {};
  byId("provider-result").textContent = `OpenAI：${providerState.llm_providers?.openai ? "已保存" : "未配置"} · DeepSeek：${providerState.llm_providers?.deepseek ? "已保存" : "未配置"} · Tavily：${providerState.web_search?.configured ? "已保存" : "未配置"}`;
  for (const role of ["fast", "smart", "strategic"]) {
    const configured = providerState.roles?.[role] || "openai:gpt-5.4";
    const separator = configured.indexOf(":");
    byId(`${role}-provider`).value = separator > 0 ? configured.slice(0, separator) : "openai";
    byId(`${role}-model`).value = separator > 0 ? configured.slice(separator + 1) : configured;
  }
  byId("cloud-server").textContent = state.status.cloud_server || "未配置";
  if (!byId("cloud-server-input").value) byId("cloud-server-input").value = state.status.cloud_server || "";
  const connected = state.status.cloud_token_configured;
  const cloudPill = byId("cloud-status-pill");
  cloudPill.classList.toggle("connected", connected);
  cloudPill.querySelector("span").textContent = connected ? "Cloud 已连接" : "Cloud 未连接";
  byId("transfer-cloud-state").textContent = connected ? "Cloud 已连接" : "Cloud 未连接";
  byId("transfer-cloud-state").classList.toggle("connected", connected);
}

async function loadCloudKbs() {
  state.cloudKbs = [];
  if (state.status?.cloud_token_configured) {
    try { state.cloudKbs = await request("/api/local/cloud-kbs"); }
    catch (_) { notify("云端已配置，但知识库列表暂时不可用。", "error"); }
  }
  renderKbOptions();
}

async function loadKbs() {
  state.kbs = await request("/api/local/kbs");
  renderKbChips();
  renderKbOptions();
  if (state.tasks.length) renderTasks();
}

async function loadTasks() {
  state.tasks = await request("/api/local/research");
  renderTasks();
}

function routeFromHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  if (raw.startsWith("result/")) return { route: "result", taskId: raw.slice(7) };
  const route = raw || "research";
  return { route: document.querySelector(`[data-view="${CSS.escape(route)}"]`) ? route : "research" };
}

function navigate(route) {
  if (route === "result") return;
  location.hash = route === "research" ? "#/research" : `#/${route}`;
}

function renderRoute(route) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.dataset.view === route));
  const navRoute = route === "result" ? "history" : route;
  document.querySelectorAll(".nav-item, .mobile-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.route === navRoute);
  });
  window.scrollTo({ top: 0, behavior: "auto" });
  if (route === "knowledge") loadKnowledgeTable();
  if (route === "transfers") loadTransferOverview();
}

function bindRouteButtons(root = document) {
  root.querySelectorAll("[data-route]").forEach((button) => {
    if (button.dataset.routeBound) return;
    button.dataset.routeBound = "true";
    button.addEventListener("click", () => navigate(button.dataset.route));
  });
}

window.addEventListener("hashchange", () => {
  const { route, taskId } = routeFromHash();
  if (route === "result" && taskId) openResult(taskId);
  else renderRoute(route);
});

byId("research-query").addEventListener("input", (event) => {
  byId("query-count").textContent = `${event.target.value.length} / 5000`;
});

byId("research").addEventListener("click", async () => {
  const query = byId("research-query").value.trim();
  const knowledgeBaseIds = [...state.selectedKbs];
  if (!query) return notify("请先填写研究问题。", "error");
  if (!knowledgeBaseIds.length) return notify("请至少选择一个本地知识库。", "error");
  const button = byId("research");
  setBusy(button, true, "正在提交…");
  try {
    const requiredClaims = byId("required-claims").value.split("\n").map((claim) => claim.trim()).filter(Boolean);
    const sourceTypes = [...document.querySelectorAll('input[name="source-type"]:checked')].map((input) => input.value);
    const asOf = byId("research-as-of").value;
    const payload = {
      query,
      knowledge_base_ids: knowledgeBaseIds,
      required_claims: requiredClaims,
      required_source_types: sourceTypes,
      minimum_distinct_sources: Number(byId("minimum-sources").value),
      require_current_version: byId("require-current").checked,
      max_deep_calls: Number(byId("max-deep-calls").value),
      output_language: byId("output-language").value,
      research_depth: byId("research-depth").value,
    };
    if (asOf) payload.as_of = new Date(asOf).toISOString();
    const task = await request("/api/local/research", { method: "POST", body: JSON.stringify(payload) });
    state.tasks.unshift({ id: task.task_id, query, knowledge_base_ids: knowledgeBaseIds, status: task.status, phase: "queued", progress_percent: 0, evidence_count: 0, created_at: new Date().toISOString() });
    renderTasks();
    showResult(task.task_id);
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

function showResult(taskId) {
  const target = `#/result/${taskId}`;
  if (location.hash === target) openResult(taskId);
  else location.hash = target;
}

async function openResult(taskId) {
  state.currentTaskId = taskId;
  renderRoute("result");
  resetResult();
  try {
    const task = await request(`/api/local/research/${taskId}`);
    renderResultTask(task);
    if (task.status === "completed") await loadArtifacts(taskId);
    else if (task.status === "failed") renderTaskFailure(task);
    else pollResearch(taskId);
  } catch (error) { notify(error.message, "error"); }
}

function resetResult() {
  state.sources = [];
  state.trace = [];
  byId("result-loading").hidden = false;
  byId("report-content").hidden = true;
  byId("report-content").replaceChildren();
  byId("report-outline").replaceChildren();
  byId("sources-list").replaceChildren();
  byId("source-detail").replaceChildren();
  byId("trace-flow").replaceChildren();
  byId("version-decisions").replaceChildren();
  byId("metrics-list").replaceChildren();
  byId("source-count").textContent = "0 个来源";
  byId("result-loading").querySelector(".loading-spinner").hidden = false;
  byId("progress-title").textContent = "正在准备研究";
  byId("progress-phase").textContent = "等待开始";
  byId("progress-evidence").textContent = "已收集 0 个证据碎片";
  byId("progress-detail").textContent = "结果会在任务完成后自动显示。";
  byId("progress-bar").style.width = "0%";
  byId("progress-bar").parentElement.setAttribute("aria-valuenow", "0");
  byId("download-md").disabled = true;
  byId("download-pdf").disabled = true;
}

function renderResultTask(task) {
  byId("result-title").textContent = task.query;
  const badge = byId("result-status");
  badge.className = `status-badge ${task.status}`;
  badge.textContent = statusLabel(task.status);
  const percent = task.status === "completed" ? 100 : Math.max(0, Math.min(99, Number(task.progress_percent) || 0));
  const evidenceCount = Math.max(0, Number(task.evidence_count) || 0);
  byId("progress-title").textContent = phaseLabel(task.phase);
  byId("progress-phase").textContent = `${phaseLabel(task.phase)} · ${percent}%`;
  byId("progress-evidence").textContent = `已收集 ${evidenceCount} 个证据碎片`;
  byId("progress-detail").textContent = `${elapsedLabel(task.started_at)}${task.started_at ? " · " : ""}阶段进度表示工作流位置，不代表剩余时间。`;
  byId("progress-bar").style.width = `${percent}%`;
  byId("progress-bar").parentElement.setAttribute("aria-valuenow", String(percent));
  if (task.status !== "completed") byId("source-count").textContent = `${evidenceCount} 个证据碎片`;
}

function renderTaskFailure(task) {
  const loading = byId("result-loading");
  loading.querySelector(".loading-spinner").hidden = true;
  byId("progress-title").textContent = "研究未完成";
  byId("progress-detail").textContent = task.error?.message || "Research task failed";
}

async function pollResearch(taskId) {
  if (state.pollingTaskId === taskId) return;
  state.pollingTaskId = taskId;
  try {
    while (state.currentTaskId === taskId) {
      const task = await request(`/api/local/research/${taskId}`);
      renderResultTask(task);
      if (task.status === "completed") {
        await loadArtifacts(taskId);
        await loadTasks();
        notify("研究已完成，报告和证据已加载。");
        return;
      }
      if (task.status === "failed") {
        renderTaskFailure(task);
        await loadTasks();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 750));
    }
  } catch (error) { notify(error.message, "error"); }
  finally { if (state.pollingTaskId === taskId) state.pollingTaskId = null; }
}

async function loadArtifacts(taskId) {
  const [report, sources, trace, metrics] = await Promise.all([
    requestText(`/api/local/research/${taskId}/report`),
    request(`/api/local/research/${taskId}/sources`),
    request(`/api/local/research/${taskId}/trace`),
    request(`/api/local/research/${taskId}/metrics`),
  ]);
  if (state.currentTaskId !== taskId) return;
  state.sources = Array.isArray(sources) ? sources : [];
  state.trace = Array.isArray(trace) ? trace : [];
  byId("result-loading").hidden = true;
  byId("report-content").hidden = false;
  renderReport(report);
  renderSources();
  renderTrace();
  renderVersions();
  renderMetrics(metrics);
  byId("download-md").disabled = false;
  byId("download-pdf").disabled = false;
}

function setReportWidth(width) {
  const selected = ["narrow", "standard", "wide"].includes(width) ? width : "standard";
  const reader = byId("report-reader");
  reader.classList.remove("width-narrow", "width-standard", "width-wide");
  reader.classList.add(`width-${selected}`);
  document.querySelectorAll("[data-report-width]").forEach((button) => {
    const active = button.dataset.reportWidth === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  try { localStorage.setItem("drkb-report-width", selected); } catch (_error) { /* optional */ }
}

async function downloadReport(format) {
  if (!state.currentTaskId) return;
  const button = byId(`download-${format}`);
  setBusy(button, true, "生成中…");
  try {
    const response = await fetch(`/api/local/research/${encodeURIComponent(state.currentTaskId)}/download?format=${format}`, {
      headers: { Accept: format === "pdf" ? "application/pdf" : "text/markdown" },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail?.message || "报告下载失败");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `research-${state.currentTaskId}.${format}`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
}

function appendInline(target, text) {
  const pattern = /(\[\d+\]|\*\*[^*]+\*\*|`[^`]+`)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) target.append(document.createTextNode(text.slice(cursor, match.index)));
    const token = match[0];
    if (/^\[\d+\]$/.test(token)) {
      const index = Number(token.slice(1, -1)) - 1;
      const button = document.createElement("button");
      button.className = "citation";
      button.textContent = token;
      button.title = `查看来源 ${index + 1}`;
      button.addEventListener("click", () => selectSource(index));
      target.append(button);
    } else if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      target.append(strong);
    } else {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      target.append(code);
    }
    cursor = match.index + token.length;
  }
  if (cursor < text.length) target.append(document.createTextNode(text.slice(cursor)));
}

function renderReport(markdown) {
  const content = byId("report-content");
  const outline = byId("report-outline");
  let list = null;
  markdown.split(/\r?\n/).forEach((line) => {
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (heading) {
      list = null;
      const level = heading[1].length;
      const element = document.createElement(`h${level}`);
      const id = `report-heading-${outline.children.length}`;
      element.id = id;
      appendInline(element, heading[2]);
      content.append(element);
      const link = document.createElement("button");
      link.className = `level-${level}`;
      link.textContent = heading[2].replace(/\*\*/g, "");
      link.addEventListener("click", () => element.scrollIntoView({ behavior: "smooth", block: "start" }));
      outline.append(link);
    } else if (bullet) {
      if (!list) { list = document.createElement("ul"); content.append(list); }
      const item = document.createElement("li");
      appendInline(item, bullet[1]);
      list.append(item);
    } else if (line.trim()) {
      list = null;
      const paragraph = document.createElement("p");
      appendInline(paragraph, line);
      content.append(paragraph);
    } else list = null;
  });
  if (!outline.children.length) outline.innerHTML = '<span class="kb-empty">报告没有章节标题</span>';
}

function sourceTitle(source) {
  return source.title || source.logical_path || source.source_uri || `来源 ${state.sources.indexOf(source) + 1}`;
}

function renderSources() {
  byId("source-count").textContent = `${state.sources.length} 个来源`;
  const target = byId("sources-list");
  if (!state.sources.length) {
    target.innerHTML = '<div class="empty-state">本次报告没有可展示的来源。</div>';
    return;
  }
  target.innerHTML = state.sources.map((source, index) => `
    <button class="source-item" data-source-index="${index}"><span class="source-number">${index + 1}</span><span><strong>${escapeHtml(sourceTitle(source))}</strong><small>${escapeHtml(sourceTypeLabel(source.source_type))} · v${escapeHtml(source.version || "—")}</small></span></button>`).join("");
  target.querySelectorAll("[data-source-index]").forEach((button) => button.addEventListener("click", () => selectSource(Number(button.dataset.sourceIndex))));
  selectSource(0, false);
}

function selectSource(index, switchTab = true) {
  const source = state.sources[index];
  if (!source) return;
  if (switchTab) activateInspector("sources");
  byId("sources-list").querySelectorAll(".source-item").forEach((item, itemIndex) => item.classList.toggle("active", itemIndex === index));
  const satisfied = state.trace.some((step) => (step.decisions || []).some((decision) => String(decision.reason || "").includes("requirements satisfied")));
  byId("source-detail").innerHTML = `
    <h3>${escapeHtml(sourceTitle(source))}</h3>
    <dl>
      <div><dt>来源类型</dt><dd>${escapeHtml(sourceTypeLabel(source.source_type))}</dd></div>
      <div><dt>知识库</dt><dd>${escapeHtml(kbName(source.knowledge_base_id))}</dd></div>
      <div><dt>文档版本</dt><dd>v${escapeHtml(source.version || "—")}</dd></div>
      <div><dt>版本状态</dt><dd>${source.status === "active" ? "Current" : "Historical"}</dd></div>
      <div><dt>Source URI</dt><dd>${escapeHtml(source.source_uri || "—")}</dd></div>
      <div><dt>证据要求</dt><dd>${satisfied ? "已满足" : "已纳入，需结合整体证据审计"}</dd></div>
    </dl>
    ${source.text ? `<blockquote>${escapeHtml(source.text)}</blockquote>` : ""}`;
}

function renderTrace() {
  const finalRoute = state.trace.at(-1)?.final_route;
  const hasQuick = state.trace.some((step) => (step.quick_evidence || []).length);
  const hasDeep = state.trace.some((step) => (step.deep_evidence || []).length);
  const steps = [
    ["Plan", state.trace.length ? "已生成研究计划" : "研究计划已接收"],
    ["Retrieve", `${state.sources.length} 条最终证据`],
    ["Sufficiency Check", state.trace.length ? "已执行证据充分性判断" : "未提供详细轨迹"],
    ["Quick / Deep Research", hasDeep ? "执行 Deep Research" : hasQuick ? "执行 Quick Research" : finalRoute === "stop" ? "已有证据充分，停止扩展" : "未触发外部扩展"],
    ["Synthesis", "已生成研究报告"],
    ["Completed", "研究任务完成"],
  ];
  byId("trace-flow").innerHTML = steps.map(([title, detail]) => `<div class="trace-step"><i>✓</i><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div></div>`).join("");
}

function renderVersions() {
  const decisions = state.sources.filter((source) => source.version || source.version_selection_reason);
  byId("version-decisions").innerHTML = decisions.length ? decisions.map((source) => `
    <div class="version-card"><strong>${escapeHtml(sourceTitle(source))}</strong><span>v${escapeHtml(source.version || "—")} · ${source.status === "active" ? "Current" : "Historical"}</span><span>${escapeHtml(source.version_selection_reason || "使用检索选中的文档版本")}</span></div>`).join("") : '<div class="empty-state">没有版本决策记录。</div>';
}

function renderMetrics(metrics) {
  const entries = Object.entries(metrics || {});
  byId("metrics-list").innerHTML = entries.length ? entries.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(typeof value === "object" ? JSON.stringify(value) : value)}</dd></div>`).join("") : '<div class="empty-state">没有指标数据。</div>';
}

function activateInspector(name) {
  document.querySelectorAll("[data-inspector]").forEach((button) => button.classList.toggle("active", button.dataset.inspector === name));
  document.querySelectorAll("[data-inspector-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.inspectorPanel === name));
  if (window.innerWidth < 761) byId("source-count").scrollIntoView({ behavior: "smooth", block: "start" });
}

document.querySelectorAll("[data-inspector]").forEach((button) => button.addEventListener("click", () => activateInspector(button.dataset.inspector)));

byId("kb-create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = byId("local-kb-name").value.trim();
  if (!name) return notify("请填写知识库名称。", "error");
  try {
    const created = await request("/api/local/kbs", { method: "POST", body: JSON.stringify({ name }) });
    byId("local-kb-name").value = "";
    await loadKbs();
    state.selectedKbs.add(created.id);
    renderKbChips();
    await loadKnowledgeTable();
    notify("本地知识库已创建。");
  } catch (error) { notify(error.message, "error"); }
});

async function loadKnowledgeTable() {
  if (!state.kbs.length) {
    byId("knowledge-table").replaceChildren();
    byId("knowledge-empty").hidden = false;
    return;
  }
  const rows = await Promise.all(state.kbs.map(async (kb) => {
    try { return { kb, documents: await request(`/api/local/kbs/${kb.id}/documents`) }; }
    catch (_) { return { kb, documents: [] }; }
  }));
  byId("knowledge-empty").hidden = true;
  byId("knowledge-table").innerHTML = rows.map(({ kb, documents }) => {
    const updated = documents.map((document) => document.updated_at).filter(Boolean).sort().at(-1);
    return `<tr><td><div class="task-title"><svg><use href="#i-database"></use></svg><span>${escapeHtml(kb.name)}</span></div></td><td>${documents.length}</td><td>${escapeHtml(formatDate(updated))}</td><td>${escapeHtml(formatDate(kb.created_at))}</td></tr>`;
  }).join("");
}

byId("scan").addEventListener("click", async () => {
  const button = byId("scan");
  setBusy(button, true, "扫描中…");
  try {
    const result = await request("/api/local/scan", { method: "POST", body: JSON.stringify({ directory: byId("directory").value }) });
    byId("scan-summary").innerHTML = result.files.length
      ? `<div class="scan-head"><strong>${result.count} 个支持的文件</strong><span>${escapeHtml(result.directory)}</span></div><ol>${result.files.map((file) => `<li><code>${escapeHtml(file.logical_path)}</code><span>${formatBytes(file.size_bytes)}</span></li>`).join("")}</ol>`
      : '<div class="empty-state">目录中没有支持的文件。</div>';
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("ingest").addEventListener("click", async () => {
  const kbId = byId("file-local-kb").value;
  if (!kbId) return notify("请选择目标本地知识库。", "error");
  const button = byId("ingest");
  setBusy(button, true, "导入中…");
  try {
    const result = await request("/api/local/ingest", { method: "POST", body: JSON.stringify({ directory: byId("directory").value, kb_id: kbId }) });
    byId("ingest-result").hidden = false;
    const labels = { ValueError: "内容无法解析", UnicodeDecodeError: "文本编码无法读取", PermissionError: "没有读取权限", OSError: "文件读取失败" };
    const errors = result.errors || [];
    const breakdown = Object.entries(errors.reduce((counts, item) => {
      counts[item.error_type] = (counts[item.error_type] || 0) + 1;
      return counts;
    }, {})).map(([type, count]) => `${labels[type] || type} ${count}`).join(" · ");
    const examples = errors.slice(0, 8).map((item) => `<li><code>${escapeHtml(item.logical_path)}</code><span>${escapeHtml(labels[item.error_type] || item.error_type)}</span></li>`).join("");
    byId("ingest-result").innerHTML = `<strong>导入完成</strong>：新增版本 ${result.imported} · 未变化 ${result.unchanged} · 失败 ${result.failed}${breakdown ? `<div class="ingest-errors">失败类型：${escapeHtml(breakdown)}${examples ? `<details><summary>查看失败文件（最多 8 项）</summary><ul>${examples}</ul></details>` : ""}</div>` : ""}`;
    notify(result.failed ? `导入完成，但有 ${result.failed} 个文件失败。` : "本地文件已导入知识库。", result.failed ? "error" : "success");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

function updateTransferButtons() {
  const ready = Boolean(state.status?.cloud_token_configured && byId("transfer-local-kb").value && byId("transfer-cloud-kb").value);
  byId("sync-push").disabled = !ready;
  byId("sync-pull").disabled = !ready;
}

async function loadTransferOverview() {
  updateTransferButtons();
  const localId = byId("transfer-local-kb").value;
  const cloudId = byId("transfer-cloud-kb").value;
  if (!localId || !cloudId || !state.status?.cloud_token_configured) {
    ["local-doc-count", "local-updated", "cloud-doc-count", "cloud-updated"].forEach((id) => { byId(id).textContent = "—"; });
    byId("baseline-status").textContent = state.status?.cloud_token_configured ? "选择两侧知识库后显示" : "请先在设置中连接 Cloud";
    return;
  }
  try {
    const overview = await request(`/api/local/transfers/overview?local_kb_id=${encodeURIComponent(localId)}&cloud_kb_id=${encodeURIComponent(cloudId)}`);
    byId("local-doc-count").textContent = overview.local.document_count;
    byId("local-updated").textContent = formatDate(overview.local.updated_at);
    byId("cloud-doc-count").textContent = overview.cloud.document_count;
    byId("cloud-updated").textContent = formatDate(overview.cloud.updated_at);
    byId("baseline-status").textContent = overview.baseline.tracked_documents
      ? `${overview.baseline.tracked_documents} 个文档已建立共同基线`
      : "尚未建立共同基线";
  } catch (error) { notify(error.message, "error"); }
}

byId("transfer-local-kb").addEventListener("change", loadTransferOverview);
byId("transfer-cloud-kb").addEventListener("change", loadTransferOverview);

function transferSummary(result) {
  return `新增版本 ${result.imported} · 未变化 ${result.unchanged} · 冲突 ${result.conflicts || 0} · 失败 ${result.failed}`;
}

function renderTransferResult(result) {
  const reasons = {
    cloud_changed_pull_recommended: "云端已变化，建议先 Pull",
    local_changed_push_recommended: "本地已变化，建议先 Push",
    local_and_cloud_versions_differ: "本地与云端内容分叉",
  };
  const conflicts = (result.conflict_items || []).map((item) => `<li><code>${escapeHtml(item.logical_path)}</code><span>${escapeHtml(reasons[item.reason] || item.reason)}</span></li>`).join("");
  byId("sync-result").innerHTML = `<div class="transfer-summary"><div><span>Imported</span><strong>${result.imported}</strong></div><div><span>Unchanged</span><strong>${result.unchanged}</strong></div><div class="conflict"><span>Conflict</span><strong>${result.conflicts || 0}</strong></div><div><span>Failed</span><strong>${result.failed}</strong></div></div>${conflicts ? `<ul class="conflict-list">${conflicts}</ul>` : ""}`;
}

async function runTransfer(direction) {
  const localId = byId("transfer-local-kb").value;
  const cloudId = byId("transfer-cloud-kb").value;
  if (!localId || !cloudId) return notify("请选择本地和云端知识库。", "error");
  const button = byId(direction === "push" ? "sync-push" : "sync-pull");
  setBusy(button, true, direction === "push" ? "推送中…" : "拉取中…");
  try {
    const endpoint = direction === "push" ? "/api/local/sync/push" : "/api/local/pull";
    const result = await request(endpoint, { method: "POST", body: JSON.stringify({ local_kb_id: localId, cloud_kb_id: cloudId }) });
    renderTransferResult(result);
    await loadTransferOverview();
    notify(`${direction === "push" ? "Push" : "Pull"} 完成：${transferSummary(result)}`, result.conflicts ? "error" : "success");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); updateTransferButtons(); }
}

byId("sync-push").addEventListener("click", () => runTransfer("push"));
byId("sync-pull").addEventListener("click", () => runTransfer("pull"));

byId("cloud-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = byId("cloud-save");
  setBusy(button, true, "验证中…");
  try {
    await request("/api/local/cloud", { method: "PUT", body: JSON.stringify({ server: byId("cloud-server-input").value, token: byId("cloud-token-input").value }) });
    byId("cloud-token-input").value = "";
    await loadStatus();
    await loadCloudKbs();
    notify("Cloud 连接已验证并保存，token 不会回显。");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("cloud-clear").addEventListener("click", async () => {
  try {
    await request("/api/local/cloud", { method: "DELETE" });
    byId("cloud-server-input").value = "";
    byId("cloud-token-input").value = "";
    await loadStatus();
    await loadCloudKbs();
    notify("Cloud 连接已清除，本地研究不受影响。");
  } catch (error) { notify(error.message, "error"); }
});

byId("provider-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = byId("provider-save");
  const payload = {};
  const openai = byId("openai-api-key").value.trim();
  const deepseek = byId("deepseek-api-key").value.trim();
  const tavily = byId("tavily-api-key").value.trim();
  if (openai) payload.openai_api_key = openai;
  if (deepseek) payload.deepseek_api_key = deepseek;
  if (tavily) payload.tavily_api_key = tavily;
  const openaiBase = byId("openai-base-url").value.trim();
  const deepseekBase = byId("deepseek-base-url").value.trim();
  if (openaiBase) payload.openai_base_url = openaiBase;
  if (deepseekBase) payload.deepseek_base_url = deepseekBase;
  for (const role of ["fast", "smart", "strategic"]) {
    const model = byId(`${role}-model`).value.trim();
    if (!model) return notify(`请填写 ${role} 模型名称。`, "error");
    payload[`${role}_llm`] = `${byId(`${role}-provider`).value}:${model}`;
  }
  setBusy(button, true, "保存中…");
  try {
    await request("/api/local/providers", { method: "PUT", body: JSON.stringify(payload) });
    byId("openai-api-key").value = "";
    byId("deepseek-api-key").value = "";
    byId("tavily-api-key").value = "";
    byId("tavily-api-key").value = "";
    await loadStatus();
    notify("本机 Provider 已保存，密钥不会回显。");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("provider-clear").addEventListener("click", async () => {
  try {
    await request("/api/local/providers", { method: "DELETE" });
    await loadStatus();
    notify("本机 Provider 密钥已清除。", "success");
  } catch (error) { notify(error.message, "error"); }
});

byId("backup").addEventListener("click", async () => {
  const button = byId("backup");
  setBusy(button, true, "生成中…");
  try {
    const result = await request("/api/local/backups", { method: "POST" });
    byId("backup-result").textContent = `已保存 ${result.relative_path} · ${formatBytes(result.size_bytes)}`;
    notify("一致性备份已下载到允许目录。");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

document.querySelectorAll("[data-report-width]").forEach((button) => {
  button.addEventListener("click", () => setReportWidth(button.dataset.reportWidth));
});
byId("download-md").addEventListener("click", () => downloadReport("md"));
byId("download-pdf").addEventListener("click", () => downloadReport("pdf"));

async function initialize() {
  bindRouteButtons();
  let reportWidth = "standard";
  try { reportWidth = localStorage.getItem("drkb-report-width") || reportWidth; } catch (_error) { /* optional */ }
  setReportWidth(reportWidth);
  await Promise.all([loadStatus(), loadKbs(), loadTasks()]);
  await loadCloudKbs();
  const { route, taskId } = routeFromHash();
  if (route === "result" && taskId) await openResult(taskId);
  else renderRoute(route);
}

initialize().catch((error) => notify(error.message, "error"));
