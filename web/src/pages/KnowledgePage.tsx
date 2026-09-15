import { useEffect, useMemo, useState, type DragEvent, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  Database,
  FileText,
  Folder,
  History,
  Pencil,
  Plus,
  UploadCloud,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  createKnowledgeBase,
  getDocument,
  getVersion,
  listDocuments,
  listKnowledgeBases,
  listVersions,
  renameKnowledgeBase,
  uploadDocument,
} from "../api";
import { EmptyState, ErrorState, LoadingState } from "../components/UiState";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

export default function KnowledgePage() {
  const { kbId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const kbs = useQuery({ queryKey: ["kbs"], queryFn: listKnowledgeBases });

  const createKb = useMutation({
    mutationFn: createKnowledgeBase,
    onSuccess: async (kb) => {
      setNewName("");
      await queryClient.invalidateQueries({ queryKey: ["kbs"] });
      navigate(`/knowledge/${kb.id}`);
    },
  });

  const submitCreate = (event: FormEvent) => {
    event.preventDefault();
    if (newName.trim()) createKb.mutate(newName.trim());
  };

  if (kbId) {
    return <KnowledgeWorkspace kbId={kbId} onBack={() => navigate("/knowledge")} />;
  }

  return (
    <div className="stack-page">
      <header className="page-heading">
        <div><span className="eyebrow">KNOWLEDGE</span><h1>知识库</h1><p>原文件、解析内容与版本 provenance 的统一入口。</p></div>
        <form className="inline-create" onSubmit={submitCreate}>
          <label className="sr-only" htmlFor="new-kb">知识库名称</label>
          <input id="new-kb" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="新知识库名称" />
          <button className="button button-primary" disabled={createKb.isPending}><Plus size={16} />新建</button>
        </form>
      </header>
      {createKb.error && <ErrorState message={createKb.error instanceof ApiError ? createKb.error.message : "创建失败"} />}
      {kbs.isLoading ? <LoadingState /> : !kbs.data?.length ? (
        <EmptyState title="还没有知识库" description="建立第一个知识空间，再上传或从本地推送文档。" />
      ) : (
        <div className="kb-grid">
          {kbs.data.map((kb) => (
            <button className="kb-card" key={kb.id} onClick={() => navigate(`/knowledge/${kb.id}`)}>
              <span className="kb-card-icon"><Database size={21} /></span>
              <strong>{kb.name}</strong>
              <small>创建于 {formatDate(kb.created_at)}</small>
              <span className="text-link">打开工作区</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function KnowledgeWorkspace({ kbId, onBack }: { kbId: string; onBack: () => void }) {
  const queryClient = useQueryClient();
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [folder, setFolder] = useState("all");
  const [uploadFolder, setUploadFolder] = useState("documents");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [name, setName] = useState("");

  const kbs = useQuery({ queryKey: ["kbs"], queryFn: listKnowledgeBases });
  const kb = kbs.data?.find((item) => item.id === kbId);
  const documents = useQuery({
    queryKey: ["documents", kbId],
    queryFn: () => listDocuments(kbId),
  });

  useEffect(() => {
    if (kb) setName(kb.name);
  }, [kb]);

  const folders = useMemo(() => Array.from(new Set(
    (documents.data ?? []).map((document) => document.logical_path.includes("/")
      ? document.logical_path.split("/").slice(0, -1).join("/")
      : "/"),
  )).sort(), [documents.data]);
  const visibleDocuments = (documents.data ?? []).filter((document) => folder === "all"
    || (folder === "/" ? !document.logical_path.includes("/") : document.logical_path.startsWith(`${folder}/`)));

  const rename = useMutation({
    mutationFn: () => renameKnowledgeBase(kbId, name),
    onSuccess: async () => {
      setEditingName(false);
      await queryClient.invalidateQueries({ queryKey: ["kbs"] });
    },
  });

  const upload = useMutation({
    mutationFn: async () => {
      if (!uploadFile) throw new Error("请选择文件");
      const cleaned = uploadFolder.trim().replace(/^\/+|\/+$/g, "");
      return uploadDocument(kbId, uploadFile, cleaned ? `${cleaned}/${uploadFile.name}` : uploadFile.name);
    },
    onSuccess: async (version) => {
      setUploadFile(null);
      setDocumentId(version.document_id);
      await queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
    },
  });

  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    setUploadFile(event.dataTransfer.files[0] ?? null);
  };

  if (kbs.isLoading || documents.isLoading) return <LoadingState label="正在打开知识库…" />;
  if (!kb) return <ErrorState message="知识库不存在或已不可访问" />;

  return (
    <div className="stack-page">
      <button className="back-button" onClick={onBack}><ArrowLeft size={16} />全部知识库</button>
      <header className="workspace-heading">
        <div className="workspace-title">
          <span className="kb-card-icon"><Database size={21} /></span>
          {editingName ? (
            <form onSubmit={(event) => { event.preventDefault(); rename.mutate(); }} className="rename-form">
              <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
              <button className="icon-button" aria-label="保存名称"><Check size={17} /></button>
            </form>
          ) : (
            <><div><span className="eyebrow">KNOWLEDGE BASE</span><h1>{kb.name}</h1></div><button className="icon-button" onClick={() => setEditingName(true)} aria-label="重命名"><Pencil size={16} /></button></>
          )}
        </div>
        <span className="muted small">ID {kb.id.slice(0, 10)}…</span>
      </header>

      <section className="upload-workbench">
        <div
          className={`drop-zone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
        >
          <UploadCloud size={24} />
          <strong>{uploadFile ? uploadFile.name : "拖入文档，或从设备选择"}</strong>
          <span>原文件上传后由既有 ingest contract 解析并产生不可变版本。</span>
          <label className="button button-secondary file-picker">
            选择文件<input type="file" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />
          </label>
        </div>
        <div className="upload-options">
          <label>目标文件夹<input value={uploadFolder} onChange={(event) => setUploadFolder(event.target.value)} placeholder="documents" /></label>
          <button className="button button-primary" disabled={!uploadFile || upload.isPending} onClick={() => upload.mutate()}>
            <UploadCloud size={16} />{upload.isPending ? "正在上传…" : "上传并解析"}
          </button>
          {upload.error && <ErrorState message={upload.error instanceof Error ? upload.error.message : "上传失败"} />}
        </div>
      </section>

      <div className="knowledge-layout">
        <aside className="folder-sidebar">
          <h2>文件夹</h2>
          <button className={folder === "all" ? "active" : ""} onClick={() => setFolder("all")}><Folder size={16} />全部文件 <span>{documents.data?.length ?? 0}</span></button>
          {folders.map((item) => (
            <button key={item} className={folder === item ? "active" : ""} onClick={() => setFolder(item)}><Folder size={16} />{item} </button>
          ))}
        </aside>
        <section className="document-browser">
          <div className="section-heading compact"><div><span className="eyebrow">DOCUMENTS</span><h2>{folder === "all" ? "全部文件" : folder}</h2></div><span className="count-pill">{visibleDocuments.length}</span></div>
          {!visibleDocuments.length ? <EmptyState title="文件夹为空" description="上传原文件，或使用本地 push-dir 推送。" /> : (
            <div className="document-list">
              {visibleDocuments.map((document) => (
                <button key={document.id} className={documentId === document.id ? "active" : ""} onClick={() => setDocumentId(document.id)}>
                  <FileText size={17} /><span><strong>{document.logical_path.split("/").at(-1)}</strong><small>{document.logical_path}</small></span>
                </button>
              ))}
            </div>
          )}
        </section>
        <section className="document-inspector">
          {documentId ? <DocumentInspector kbId={kbId} documentId={documentId} /> : <EmptyState title="选择一个文档" description="查看当前解析预览、版本时间线和 provenance。" />}
        </section>
      </div>
    </div>
  );
}

function DocumentInspector({ kbId, documentId }: { kbId: string; documentId: string }) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const detail = useQuery({ queryKey: ["document", kbId, documentId], queryFn: () => getDocument(kbId, documentId) });
  const versions = useQuery({ queryKey: ["versions", kbId, documentId], queryFn: () => listVersions(kbId, documentId) });
  const version = useQuery({
    queryKey: ["version", kbId, documentId, selectedVersion],
    queryFn: () => getVersion(kbId, documentId, selectedVersion!),
    enabled: selectedVersion !== null,
  });

  useEffect(() => setSelectedVersion(null), [documentId]);
  if (detail.isLoading || versions.isLoading) return <LoadingState />;
  if (!detail.data) return <ErrorState message="文档详情不可用" />;
  const content = selectedVersion ? version.data?.parsed_content : detail.data.parsed_content_preview;

  return (
    <div className="inspector-content">
      <div className="inspector-heading"><FileText size={19} /><div><h2>{detail.data.logical_path.split("/").at(-1)}</h2><span>{detail.data.logical_path}</span></div></div>
      <dl className="metadata-grid">
        <div><dt>当前版本</dt><dd>v{detail.data.current_version}</dd></div>
        <div><dt>来源</dt><dd>{detail.data.source_type}</dd></div>
        <div><dt>更新时间</dt><dd>{formatDate(detail.data.updated_at)}</dd></div>
        <div><dt>状态</dt><dd><span className="success-text">{detail.data.status}</span></dd></div>
      </dl>
      <div className="version-strip">
        <span><History size={15} />版本</span>
        <button className={selectedVersion === null ? "active" : ""} onClick={() => setSelectedVersion(null)}>当前预览</button>
        {versions.data?.map((item) => <button key={item.version} className={selectedVersion === item.version ? "active" : ""} onClick={() => setSelectedVersion(item.version)}>v{item.version}</button>)}
      </div>
      <article className="parsed-preview">
        <div className="preview-label">{selectedVersion ? `VERSION ${selectedVersion} · FULL PARSED CONTENT` : "CURRENT · PARSED CONTENT PREVIEW"}</div>
        {version.isLoading ? <LoadingState /> : <pre>{content || "没有可显示的解析文本"}</pre>}
      </article>
      <details className="provenance-details">
        <summary>Provenance</summary>
        <dl>
          <div><dt>Source URI</dt><dd>{selectedVersion ? version.data?.source_uri : detail.data.source_uri}</dd></div>
          <div><dt>Content hash</dt><dd className="mono">{selectedVersion ? version.data?.content_hash : detail.data.content_hash}</dd></div>
          <div><dt>Ingested</dt><dd>{formatDate(selectedVersion && version.data ? version.data.ingested_at : detail.data.ingested_at)}</dd></div>
        </dl>
      </details>
    </div>
  );
}
