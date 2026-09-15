import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, GitBranch, Library, TimerReset } from "lucide-react";
import { Link } from "react-router-dom";
import { listKnowledgeBases, listResearch } from "../api";
import ResearchComposer from "../components/ResearchComposer";
import StatusBadge from "../components/StatusBadge";
import { EmptyState } from "../components/UiState";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

export default function HomePage() {
  const kbs = useQuery({ queryKey: ["kbs"], queryFn: listKnowledgeBases });
  const tasks = useQuery({
    queryKey: ["research"],
    queryFn: listResearch,
    refetchInterval: (query) => query.state.data?.some(
      (task) => task.status === "queued" || task.status === "running") ? 1500 : false,
  });

  return (
    <div className="home-layout">
      <section className="home-main">
        <ResearchComposer />
        <div className="section-heading">
          <div><span className="eyebrow">RECENT WORK</span><h2>最近研究</h2></div>
          <span className="muted small">单进程任务记录</span>
        </div>
        <div className="task-list">
          {!tasks.data?.length ? (
            <EmptyState title="还没有研究任务" description="从上方写下第一个需要证据支持的问题。" />
          ) : tasks.data.slice(0, 6).map((task) => (
            <Link className="task-row" to={`/research/${task.id}`} key={task.id}>
              <span className="task-icon"><TimerReset size={18} /></span>
              <span className="task-copy">
                <strong>{task.query.split("\n")[0]}</strong>
                <small>{formatDate(task.created_at)}</small>
              </span>
              <StatusBadge status={task.status} />
              <ArrowRight size={16} />
            </Link>
          ))}
        </div>
      </section>

      <aside className="home-aside">
        <section className="side-card">
          <div className="side-card-heading"><Library size={18} /><h2>知识库</h2></div>
          <strong className="large-number">{kbs.data?.length ?? "—"}</strong>
          <span className="muted">个可选知识空间</span>
          <div className="mini-list">
            {(kbs.data ?? []).slice(0, 4).map((kb) => (
              <Link to={`/knowledge/${kb.id}`} key={kb.id}>
                <Database size={15} /><span>{kb.name}</span><ArrowRight size={14} />
              </Link>
            ))}
          </div>
          <Link to="/knowledge" className="text-link">管理知识库 <ArrowRight size={14} /></Link>
        </section>

        <section className="side-card pathway-card">
          <div className="side-card-heading"><GitBranch size={18} /><h2>Evidence pathway</h2></div>
          <div className="pathway">
            <div><span>1</span><p><strong>Internal</strong><small>先检查受治理的内部知识</small></p></div>
            <div><span>2</span><p><strong>Quick</strong><small>证据不足时补充外部来源</small></p></div>
            <div><span>3</span><p><strong>Deep</strong><small>冲突或缺口仍在时再升级</small></p></div>
          </div>
          <p className="card-note">路径由 Evidence Contract 与当前证据决定，页面不复刻路由逻辑。</p>
        </section>
      </aside>
    </div>
  );
}
