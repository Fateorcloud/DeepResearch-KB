import { useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  FilePlus2,
  FolderOpen,
  Link2,
  Play,
  Plus,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  createResearch,
  listKnowledgeBases,
  uploadDocument,
} from "../api";
import type { ResearchInput, SourceType } from "../types";

function cleanFolder(value: string) {
  return value.trim().replace(/^\/+|\/+$/g, "");
}

export default function ResearchComposer() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [selectedKbs, setSelectedKbs] = useState<string[]>([]);
  const [claims, setClaims] = useState("");
  const [sourceTypes, setSourceTypes] = useState<SourceType[]>([]);
  const [minimumSources, setMinimumSources] = useState(1);
  const [currentOnly, setCurrentOnly] = useState(true);
  const [asOf, setAsOf] = useState("");
  const [maxDeepCalls, setMaxDeepCalls] = useState(1);
  const [advanced, setAdvanced] = useState(false);
  const [linksOpen, setLinksOpen] = useState(false);
  const [links, setLinks] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [attachmentKb, setAttachmentKb] = useState("");
  const [attachmentFolder, setAttachmentFolder] = useState("attachments");
  const [error, setError] = useState("");

  const kbs = useQuery({ queryKey: ["kbs"], queryFn: listKnowledgeBases });
  const kbById = useMemo(
    () => new Map((kbs.data ?? []).map((kb) => [kb.id, kb.name])),
    [kbs.data],
  );

  const mutation = useMutation({
    mutationFn: async () => {
      const requiredClaims = claims.split("\n").map((item) => item.trim()).filter(Boolean);
      if (!query.trim()) throw new Error("请先写下研究问题");
      if (!requiredClaims.length) throw new Error("请至少填写一条报告必须回答的内容");
      if (files.length && !attachmentKb) throw new Error("请为附件选择目标知识库");

      const folder = cleanFolder(attachmentFolder);
      for (const file of files) {
        const logicalPath = folder ? `${folder}/${file.name}` : file.name;
        await uploadDocument(attachmentKb, file, logicalPath);
      }
      if (files.length) {
        await queryClient.invalidateQueries({ queryKey: ["documents", attachmentKb] });
      }

      const referenceLinks = links.split("\n").map((item) => item.trim()).filter(Boolean);
      const queryWithLinks = referenceLinks.length
        ? `${query.trim()}\n\n用户提供的参考链接：\n${referenceLinks.map((link) => `- ${link}`).join("\n")}`
        : query.trim();
      const body: ResearchInput = {
        query: queryWithLinks,
        knowledge_base_ids: selectedKbs,
        required_claims: requiredClaims,
        required_source_types: sourceTypes,
        minimum_distinct_sources: minimumSources,
        require_current_version: currentOnly,
        max_deep_calls: maxDeepCalls,
        ...(asOf ? { as_of: new Date(asOf).toISOString() } : {}),
      };
      return createResearch(body);
    },
    onSuccess: ({ task_id }) => {
      void queryClient.invalidateQueries({ queryKey: ["research"] });
      navigate(`/research/${task_id}`);
    },
    onError: (reason) => {
      setError(reason instanceof ApiError || reason instanceof Error ? reason.message : "研究任务创建失败");
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    mutation.mutate();
  };

  const toggleKb = (id: string) => {
    setSelectedKbs((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]);
  };

  const toggleSource = (source: SourceType) => {
    setSourceTypes((current) => current.includes(source)
      ? current.filter((item) => item !== source)
      : [...current, source]);
  };

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-heading">
        <div>
          <span className="eyebrow"><Plus size={13} />NEW RESEARCH</span>
          <h1>今天要研究什么？</h1>
        </div>
        <span className="seam-label">Evidence-first</span>
      </div>

      <label className="sr-only" htmlFor="research-query">研究问题</label>
      <textarea
        id="research-query"
        className="composer-textarea"
        placeholder="描述背景、限制和你真正需要做出的判断。问题越具体，证据链越容易核查。"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="composer-context">
        <div className="context-group">
          <span className="context-label"><FolderOpen size={15} />知识库</span>
          <div className="chip-row">
            {(kbs.data ?? []).map((kb) => (
              <button
                type="button"
                key={kb.id}
                className={`select-chip ${selectedKbs.includes(kb.id) ? "selected" : ""}`}
                onClick={() => toggleKb(kb.id)}
              >
                {kb.name}
              </button>
            ))}
            {!kbs.isLoading && !kbs.data?.length && <span className="muted small">暂无知识库，可仅使用外部研究。</span>}
          </div>
        </div>

        <div className="composer-tools">
          <input
            ref={fileInput}
            className="sr-only"
            type="file"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          <button type="button" className="tool-button" onClick={() => fileInput.current?.click()}>
            <FilePlus2 size={16} />附件{files.length ? ` · ${files.length}` : ""}
          </button>
          <button type="button" className={`tool-button ${linksOpen ? "active" : ""}`} onClick={() => setLinksOpen(!linksOpen)}>
            <Link2 size={16} />链接
          </button>
          <button type="button" className={`tool-button ${advanced ? "active" : ""}`} onClick={() => setAdvanced(!advanced)}>
            <SlidersHorizontal size={16} />Evidence Contract<ChevronDown size={14} />
          </button>
        </div>
      </div>

      {files.length > 0 && (
        <div className="composer-panel attachment-panel">
          <div className="field-grid two">
            <label>
              附件写入知识库
              <select value={attachmentKb} onChange={(event) => setAttachmentKb(event.target.value)} required>
                <option value="">选择知识库</option>
                {(kbs.data ?? []).map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
              </select>
            </label>
            <label>
              文件夹路径
              <input value={attachmentFolder} onChange={(event) => setAttachmentFolder(event.target.value)} placeholder="attachments" />
              <span className="field-help">仅用于上传 logical path；Research 当前仍按整个知识库取证。</span>
            </label>
          </div>
          <div className="file-list">
            {files.map((file, index) => (
              <span className="file-chip" key={`${file.name}-${index}`}>
                {file.name}
                <button type="button" aria-label={`移除 ${file.name}`} onClick={() => setFiles(files.filter((_, item) => item !== index))}>
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {linksOpen && (
        <div className="composer-panel">
          <label>
            参考链接，每行一个
            <textarea className="compact-textarea" value={links} onChange={(event) => setLinks(event.target.value)} placeholder="https://docs.example.com/current" />
            <span className="field-help">链接会作为明确的研究指令随 query 提交。</span>
          </label>
        </div>
      )}

      {advanced && (
        <div className="composer-panel evidence-panel">
          <div className="evidence-intro">
            <div>
              <h2>Evidence Contract</h2>
              <p>把“回答得像”变成可以检查的最低证据条件。</p>
            </div>
            <span className="count-pill">{claims.split("\n").filter((item) => item.trim()).length} claims</span>
          </div>
          <label>
            报告必须回答什么？每行一条
            <textarea className="compact-textarea" value={claims} onChange={(event) => setClaims(event.target.value)} placeholder={"当前采用的架构是什么\n为什么选择该方案"} required />
          </label>
          <div className="field-grid three">
            <fieldset>
              <legend>必须使用的来源类型</legend>
              <label className="check-row"><input type="checkbox" checked={sourceTypes.includes("local_import")} onChange={() => toggleSource("local_import")} />本地推送资料</label>
              <label className="check-row"><input type="checkbox" checked={sourceTypes.includes("web_upload")} onChange={() => toggleSource("web_upload")} />Web 上传资料</label>
              <label className="check-row"><input type="checkbox" checked={sourceTypes.includes("external_web")} onChange={() => toggleSource("external_web")} />外部来源</label>
            </fieldset>
            <label>
              至少几个独立来源
              <input type="number" min="1" value={minimumSources} onChange={(event) => setMinimumSources(Number(event.target.value))} />
            </label>
            <label>
              最大 Deep 调用
              <input type="number" min="0" value={maxDeepCalls} onChange={(event) => setMaxDeepCalls(Number(event.target.value))} />
            </label>
          </div>
          <div className="field-grid two">
            <label className="check-card">
              <input type="checkbox" checked={currentOnly} onChange={(event) => setCurrentOnly(event.target.checked)} />
              <span><strong>只允许当前版本</strong><small>排除 superseded 或 deprecated 内部知识</small></span>
            </label>
            <label>
              截止时间（可选）
              <input type="datetime-local" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
            </label>
          </div>
        </div>
      )}

      {selectedKbs.length > 0 && (
        <div className="selection-summary">
          将从 {selectedKbs.map((id) => kbById.get(id)).filter(Boolean).join("、")} 中检索内部证据
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}
      <div className="composer-footer">
        <span>任务提交后可继续浏览，状态和工件会独立保存到当前进程。</span>
        <button className="button button-primary" disabled={mutation.isPending}>
          <Play size={16} fill="currentColor" />{mutation.isPending ? "正在提交…" : "开始研究"}
        </button>
      </div>
    </form>
  );
}
