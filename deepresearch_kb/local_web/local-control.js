const controlToken = document.querySelector('meta[name="local-control-token"]').content;
const byId = (id) => document.getElementById(id);
const alertBox = byId("alert");

async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if ((options.method || "GET") !== "GET") {
    headers.set("X-Local-Control-Token", controlToken);
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.detail?.message || "本地控制请求失败");
  }
  return payload;
}

async function requestText(path) {
  const response = await fetch(path, { headers: { Accept: "text/markdown" } });
  if (!response.ok) throw new Error("研究报告读取失败");
  return response.text();
}

function setBusy(button, busy, busyLabel) {
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.label;
}

function notify(message, kind = "success") {
  alertBox.hidden = false;
  alertBox.className = `alert ${kind}`;
  alertBox.textContent = message;
}

function transferSummary(result) {
  const conflicts = result.conflicts ? ` · 冲突 ${result.conflicts}` : "";
  return `新增版本 ${result.imported} · 未变化 ${result.unchanged}${conflicts} · 失败 ${result.failed}`;
}

function renderTransferResult(result) {
  const target = byId("sync-result");
  const reasons = {
    cloud_changed_pull_recommended: "云端已变化，请先拉取",
    local_changed_push_recommended: "本地已变化，请先推送",
    local_and_cloud_versions_differ: "本地与云端内容分叉",
  };
  const conflicts = (result.conflict_items || []).map((item) =>
    `<li><code>${escapeHtml(item.logical_path)}</code><span>${escapeHtml(reasons[item.reason] || item.reason)}</span></li>`);
  target.innerHTML = `<strong>${transferSummary(result)}</strong>${conflicts.length ? `<ul>${conflicts.join("")}</ul>` : ""}`;
}

function replaceOptions(select, items, emptyLabel) {
  const selected = select.value;
  select.replaceChildren(new Option(emptyLabel, ""));
  for (const item of items) select.add(new Option(item.name, item.id));
  if (items.some((item) => item.id === selected)) select.value = selected;
}

async function loadStatus() {
  const [status, kbs] = await Promise.all([
    request("/api/local/status"), request("/api/local/kbs"),
  ]);
  byId("allowed-root").textContent = status.allowed_root;
  byId("cloud-server").textContent = status.cloud_server || "未配置（本地模式）";
  byId("token-status").textContent = status.cloud_token_configured ? "已配置" : "未配置";
  byId("token-status").className = status.cloud_token_configured ? "ok" : "bad";
  if (!byId("cloud-server-input").value) {
    byId("cloud-server-input").value = status.cloud_server || "";
  }
  const localSelect = byId("local-kb");
  replaceOptions(localSelect, kbs, kbs.length ? "选择本地知识库" : "本地暂无知识库");
  const select = byId("kb");
  let cloudKbs = [];
  if (status.cloud_token_configured) {
    try { cloudKbs = await request("/api/local/cloud-kbs"); } catch (_) { cloudKbs = []; }
  }
  replaceOptions(select, cloudKbs, cloudKbs.length ? "选择云端知识库" : "未配置云端连接");
}

byId("scan").addEventListener("click", async () => {
  const button = byId("scan");
  setBusy(button, true, "扫描中…");
  try {
    const result = await request("/api/local/scan", {
      method: "POST", body: JSON.stringify({ directory: byId("directory").value }),
    });
    const summary = byId("scan-summary");
    if (!result.files.length) {
      summary.innerHTML = '<div class="empty"><strong>没有支持的文件</strong><span>支持 txt、md、html、pdf、docx、csv、json。</span></div>';
    } else {
      summary.innerHTML = `<div class="scan-head"><strong>${result.count} 个文件</strong><span>${result.directory}</span></div><ol>${result.files.map((file) => `<li><code>${escapeHtml(file.logical_path)}</code><span>${formatBytes(file.size_bytes)}</span></li>`).join("")}</ol>`;
    }
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setBusy(button, false);
  }
});

byId("cloud-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await request("/api/local/cloud", { method: "PUT", body: JSON.stringify({
      server: byId("cloud-server-input").value,
      token: byId("cloud-token-input").value,
    }) });
    byId("cloud-token-input").value = "";
    notify("云端连接已验证并保存；token 不会回显。");
    await loadStatus();
  } catch (error) { notify(error.message, "error"); }
});

byId("cloud-clear").addEventListener("click", async () => {
  try {
    await request("/api/local/cloud", { method: "DELETE" });
    byId("cloud-server-input").value = "";
    byId("cloud-token-input").value = "";
    await loadStatus();
    notify("云端连接已清除，本地模式继续可用。");
  } catch (error) { notify(error.message, "error"); }
});

byId("local-kb-create").addEventListener("click", async () => {
  const name = byId("local-kb-name").value.trim();
  if (!name) return notify("请填写本地知识库名称。", "error");
  try {
    const created = await request("/api/local/kbs", {
      method: "POST", body: JSON.stringify({ name }),
    });
    byId("local-kb-name").value = "";
    await loadStatus();
    byId("local-kb").value = created.id;
    notify("本地知识库已创建。 ");
  } catch (error) { notify(error.message, "error"); }
});

byId("push").addEventListener("click", async () => {
  const kbId = byId("kb").value;
  if (!kbId) return notify("请先选择目标云端知识库。", "error");
  const button = byId("push");
  setBusy(button, true, "推送中…");
  try {
    const result = await request("/api/local/push", {
      method: "POST",
      body: JSON.stringify({ directory: byId("directory").value, kb_id: kbId }),
    });
    notify(`推送完成：${transferSummary(result)}`);
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setBusy(button, false);
  }
});

byId("sync-pull").addEventListener("click", async () => {
  const cloudKbId = byId("kb").value;
  const localKbId = byId("local-kb").value;
  if (!cloudKbId || !localKbId) return notify("请选择云端和本地知识库。", "error");
  const button = byId("sync-pull");
  setBusy(button, true, "拉取中…");
  try {
    const result = await request("/api/local/pull", { method: "POST", body: JSON.stringify({
      cloud_kb_id: cloudKbId, local_kb_id: localKbId,
    }) });
    renderTransferResult(result);
    notify(`拉取完成：${transferSummary(result)}`,
      result.conflicts ? "error" : "success");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("sync-push").addEventListener("click", async () => {
  const cloudKbId = byId("kb").value;
  const localKbId = byId("local-kb").value;
  if (!cloudKbId || !localKbId) return notify("请选择云端和本地知识库。", "error");
  const button = byId("sync-push");
  setBusy(button, true, "传输中…");
  try {
    const result = await request("/api/local/sync/push", { method: "POST", body: JSON.stringify({
      cloud_kb_id: cloudKbId, local_kb_id: localKbId,
    }) });
    renderTransferResult(result);
    notify(`推送完成：${transferSummary(result)}`,
      result.conflicts ? "error" : "success");
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

byId("research").addEventListener("click", async () => {
  const query = byId("research-query").value.trim();
  const kbId = byId("local-kb").value;
  if (!query || !kbId) return notify("请填写研究问题并选择本地知识库。", "error");
  const button = byId("research");
  setBusy(button, true, "提交中…");
  try {
    const requiredClaims = byId("required-claims").value.split("\n")
      .map((claim) => claim.trim()).filter(Boolean);
    const sourceTypes = [...document.querySelectorAll('input[name="source-type"]:checked')]
      .map((input) => input.value);
    const asOf = byId("research-as-of").value;
    const payload = {
      query,
      knowledge_base_ids: [kbId],
      required_claims: requiredClaims,
      required_source_types: sourceTypes,
      minimum_distinct_sources: Number(byId("minimum-sources").value),
      require_current_version: byId("require-current").checked,
      max_deep_calls: Number(byId("max-deep-calls").value),
    };
    if (asOf) payload.as_of = new Date(asOf).toISOString();
    byId("research-report").hidden = true;
    byId("research-artifacts").hidden = true;
    const task = await request("/api/local/research", {
      method: "POST", body: JSON.stringify(payload),
    });
    byId("research-result").querySelector("span").textContent = `任务已提交：${task.task_id} · 状态 ${task.status}`;
    notify("本地 Research 已提交，任务在 Local Control 进程中运行。");
    await pollResearch(task.task_id);
  } catch (error) { notify(error.message, "error"); }
  finally { setBusy(button, false); }
});

async function pollResearch(taskId) {
  const statusLine = byId("research-result").querySelector("span");
  for (;;) {
    const task = await request(`/api/local/research/${taskId}`);
    statusLine.textContent = `任务 ${taskId.slice(0, 12)} · ${task.status}`;
    if (task.status === "completed") {
      const report = byId("research-report");
      const [reportText, sources, trace, metrics] = await Promise.all([
        requestText(`/api/local/research/${taskId}/report`),
        request(`/api/local/research/${taskId}/sources`),
        request(`/api/local/research/${taskId}/trace`),
        request(`/api/local/research/${taskId}/metrics`),
      ]);
      report.textContent = reportText;
      report.hidden = false;
      byId("research-sources").textContent = JSON.stringify(sources, null, 2);
      byId("research-trace").textContent = JSON.stringify(trace, null, 2);
      byId("research-metrics").textContent = JSON.stringify(metrics, null, 2);
      byId("research-artifacts").hidden = false;
      notify("本地 Research 已完成，报告已加载。");
      return;
    }
    if (task.status === "failed") {
      notify(task.error?.message || "本地 Research 失败。", "error");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
}

byId("ingest").addEventListener("click", async () => {
  const kbId = byId("local-kb").value;
  if (!kbId) return notify("请先选择本地知识库。", "error");
  const button = byId("ingest");
  setBusy(button, true, "导入中…");
  try {
    const result = await request("/api/local/ingest", {
      method: "POST",
      body: JSON.stringify({ directory: byId("directory").value, kb_id: kbId }),
    });
    byId("ingest-result").textContent = transferSummary(result);
    notify("扫描目录已导入本地知识库，云端数据未被修改。");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setBusy(button, false);
  }
});

byId("backup").addEventListener("click", async () => {
  const button = byId("backup");
  setBusy(button, true, "下载中…");
  try {
    const result = await request("/api/local/backups", { method: "POST" });
    byId("backup-result").innerHTML = `已保存 <code>${escapeHtml(result.relative_path)}</code> · ${formatBytes(result.size_bytes)}`;
    notify("一致性备份已下载到允许目录。");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    setBusy(button, false);
  }
});

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span.innerHTML;
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

loadStatus().catch((error) => notify(error.message, "error"));
