import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  CircleAlert,
  Clock3,
  ExternalLink,
  GitBranch,
  Library,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link, useParams } from "react-router-dom";
import { getMetrics, getReport, getResearchTask, getSources, getTrace } from "../api";
import StatusBadge from "../components/StatusBadge";
import { ErrorState, LoadingState } from "../components/UiState";

type Tab = "report" | "sources" | "trace" | "metrics";

function stringValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export default function ResearchResultPage() {
  const { taskId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("report");
  const task = useQuery({
    queryKey: ["research", taskId],
    queryFn: () => getResearchTask(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1000 : false;
    },
  });
  const complete = task.data?.status === "completed";
  const report = useQuery({ queryKey: ["report", taskId], queryFn: () => getReport(taskId), enabled: complete });
  const sources = useQuery({ queryKey: ["sources", taskId], queryFn: () => getSources(taskId), enabled: complete });
  const trace = useQuery({ queryKey: ["trace", taskId], queryFn: () => getTrace(taskId), enabled: complete });
  const metrics = useQuery({ queryKey: ["metrics", taskId], queryFn: () => getMetrics(taskId), enabled: complete });

  if (task.isLoading) return <LoadingState label="正在读取研究任务…" />;
  if (task.error || !task.data) return <ErrorState message="研究任务不存在或不可访问" />;

  return (
    <div className="result-page">
      <Link to="/" className="back-button"><ArrowLeft size={16} />返回研究台</Link>
      <header className="result-header">
        <div>
          <span className="eyebrow">RESEARCH RESULT</span>
          <h1>{task.data.query.split("\n")[0]}</h1>
          <div className="result-meta"><StatusBadge status={task.data.status} /><span><Clock3 size={14} />{new Date(task.data.created_at).toLocaleString("zh-CN")}</span><span className="mono">{task.data.id.slice(0, 12)}</span></div>
        </div>
      </header>

      {(task.data.status === "queued" || task.data.status === "running") && (
        <section className="progress-card" aria-live="polite">
          <span className="research-orbit"><span /></span>
          <div><h2>{task.data.status === "queued" ? "任务正在排队" : "正在构建证据链"}</h2><p>可以离开这个页面；返回后任务状态仍会在当前服务进程中保留。</p></div>
        </section>
      )}

      {task.data.status === "failed" && (
        <section className="failure-card"><CircleAlert size={24} /><div><h2>研究执行失败</h2><p>{task.data.error?.message ?? "服务未能完成该任务。敏感 provider 细节不会返回浏览器。"}</p></div></section>
      )}

      {complete && (
        <section className="result-workspace">
          <div className="tab-list" role="tablist" aria-label="研究工件">
            <button role="tab" aria-selected={tab === "report"} className={tab === "report" ? "active" : ""} onClick={() => setTab("report")}><BookOpen size={16} />报告</button>
            <button role="tab" aria-selected={tab === "sources"} className={tab === "sources" ? "active" : ""} onClick={() => setTab("sources")}><Library size={16} />来源 <span>{sources.data?.length ?? 0}</span></button>
            <button role="tab" aria-selected={tab === "trace"} className={tab === "trace" ? "active" : ""} onClick={() => setTab("trace")}><GitBranch size={16} />路径</button>
            <button role="tab" aria-selected={tab === "metrics"} className={tab === "metrics" ? "active" : ""} onClick={() => setTab("metrics")}><BarChart3 size={16} />指标</button>
          </div>
          <div className="tab-panel">
            {tab === "report" && (report.isLoading ? <LoadingState /> : <article className="markdown-report"><ReactMarkdown remarkPlugins={[remarkGfm]}>{report.data ?? ""}</ReactMarkdown></article>)}
            {tab === "sources" && <SourcesPanel sources={sources.data ?? []} loading={sources.isLoading} />}
            {tab === "trace" && <TracePanel trace={trace.data ?? []} loading={trace.isLoading} />}
            {tab === "metrics" && <MetricsPanel metrics={metrics.data ?? {}} loading={metrics.isLoading} />}
          </div>
        </section>
      )}
    </div>
  );
}

function SourcesPanel({ sources, loading }: { sources: Array<Record<string, unknown>>; loading: boolean }) {
  if (loading) return <LoadingState />;
  return (
    <div className="source-grid">
      {sources.map((source, index) => {
        const uri = String(source.source_uri ?? "");
        const external = uri.startsWith("http://") || uri.startsWith("https://");
        return (
          <article className="source-card" key={String(source.chunk_id ?? index)}>
            <div className="source-card-top"><span className="source-index">{index + 1}</span><span className="source-type">{stringValue(source.source_type)}</span></div>
            <p>{stringValue(source.text)}</p>
            <dl><div><dt>Document</dt><dd>{stringValue(source.logical_path)}</dd></div><div><dt>Version</dt><dd>{stringValue(source.version)}</dd></div><div><dt>Status</dt><dd>{stringValue(source.status)}</dd></div></dl>
            {external ? <a href={uri} target="_blank" rel="noreferrer">打开来源 <ExternalLink size={14} /></a> : <span className="source-uri mono">{uri}</span>}
          </article>
        );
      })}
    </div>
  );
}

function TracePanel({ trace, loading }: { trace: Array<Record<string, unknown>>; loading: boolean }) {
  if (loading) return <LoadingState />;
  return (
    <div className="trace-list">
      {trace.map((item, index) => {
        const decisions = Array.isArray(item.decisions) ? item.decisions as Array<Record<string, unknown>> : [];
        return (
          <article className="trace-card" key={index}>
            <div className="trace-heading"><span>{index + 1}</span><div><h3>{stringValue(item.question)}</h3><p>{stringValue(item.rationale)}</p></div><strong>{stringValue(item.final_route)}</strong></div>
            <div className="trace-policy"><span>Policy · {stringValue(item.source_policy)}</span><span>{decisions.length} decisions</span></div>
            <ol>{decisions.map((decision, decisionIndex) => <li key={decisionIndex}><span>{stringValue(decision.route)}</span><p>{stringValue(decision.reason)}</p><small>{stringValue(decision.terminal_status)}</small></li>)}</ol>
          </article>
        );
      })}
    </div>
  );
}

function MetricsPanel({ metrics, loading }: { metrics: Record<string, unknown>; loading: boolean }) {
  if (loading) return <LoadingState />;
  const primary = ["status", "quick_calls", "deep_calls", "max_deep_calls", "latency_seconds", "llm_calls_completed", "llm_tokens", "actual_cost_usd"];
  return (
    <div>
      <div className="metrics-grid">
        {primary.map((key) => <div className="metric-card" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{stringValue(metrics[key])}</strong></div>)}
      </div>
      <details className="raw-details"><summary>完整 metrics JSON</summary><pre>{JSON.stringify(metrics, null, 2)}</pre></details>
    </div>
  );
}
