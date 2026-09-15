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
  return `新增版本 ${result.imported} · 未变化 ${result.unchanged} · 失败 ${result.failed}`;
}

async function loadStatus() {
  const [status, kbs] = await Promise.all([
    request("/api/local/status"), request("/api/local/kbs"),
  ]);
  byId("allowed-root").textContent = status.allowed_root;
  byId("cloud-server").textContent = status.cloud_server || "未配置（本地模式）";
  byId("token-status").textContent = status.cloud_token_configured ? "已配置" : "未配置";
  byId("token-status").className = status.cloud_token_configured ? "ok" : "bad";
  const select = byId("kb");
  select.replaceChildren(new Option(kbs.length ? "选择知识库" : "云端暂无知识库", ""));
  for (const kb of kbs) select.add(new Option(kb.name, kb.id));
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

byId("cloud-save").addEventListener("click", async () => {
  try {
    await request("/api/local/cloud", { method: "PUT", body: JSON.stringify({
      server: byId("cloud-server-input").value,
      token: byId("cloud-token-input").value,
    }) });
    byId("cloud-token-input").value = "";
    notify("云端连接已保存；token 不会回显。 ");
    await loadStatus();
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

byId("ingest").addEventListener("click", async () => {
  const kbId = byId("local-kb").value.trim();
  if (!kbId) return notify("请填写现有本地 KB ID。", "error");
  const button = byId("ingest");
  setBusy(button, true, "导入中…");
  try {
    const result = await request("/api/local/ingest", {
      method: "POST",
      body: JSON.stringify({ directory: byId("directory").value, kb_id: kbId }),
    });
    byId("ingest-result").textContent = transferSummary(result);
    notify("本地解析验证完成。云端数据未被修改。");
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
