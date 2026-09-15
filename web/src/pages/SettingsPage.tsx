import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  CheckCircle2,
  Copy,
  DatabaseBackup,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  createBackup,
  createExport,
  getProviderStatus,
  issueCliToken,
  listCliTokens,
  revokeCliToken,
} from "../api";
import type { IssuedCliToken } from "../types";
import { LoadingState } from "../components/UiState";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "尚未使用";
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<IssuedCliToken | null>(null);
  const [backupLink, setBackupLink] = useState<{ filename: string; url: string } | null>(null);
  const [exportLink, setExportLink] = useState<{ filename: string; url: string } | null>(null);
  const status = useQuery({ queryKey: ["provider-status"], queryFn: getProviderStatus });
  const tokens = useQuery({ queryKey: ["cli-tokens"], queryFn: listCliTokens });

  const issue = useMutation({
    mutationFn: issueCliToken,
    onSuccess: async (token) => {
      setIssued(token);
      setLabel("");
      await queryClient.invalidateQueries({ queryKey: ["cli-tokens"] });
    },
  });
  const revoke = useMutation({
    mutationFn: revokeCliToken,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cli-tokens"] }),
  });
  const backup = useMutation({
    mutationFn: createBackup,
    onSuccess: (artifact) => setBackupLink({ filename: artifact.filename, url: artifact.download_url }),
  });
  const archive = useMutation({
    mutationFn: createExport,
    onSuccess: (artifact) => setExportLink({ filename: artifact.filename, url: artifact.download_url }),
  });

  const createToken = (event: FormEvent) => {
    event.preventDefault();
    if (label.trim()) issue.mutate(label.trim());
  };

  return (
    <div className="stack-page settings-page">
      <header className="page-heading"><div><span className="eyebrow">SETTINGS & BACKUP</span><h1>设置与备份</h1><p>检查服务可用性，管理本地控制端凭据，并下载一致性快照。</p></div></header>

      <section className="settings-section">
        <div className="settings-section-heading"><ShieldCheck size={20} /><div><h2>Provider 状态</h2><p>只显示是否可用，不回显 key、base URL 或环境变量内容。</p></div></div>
        {status.isLoading ? <LoadingState /> : (
          <div className="provider-grid">
            <ProviderCard label="Research provider" configured={status.data?.research_provider.configured ?? false} />
            <ProviderCard label="Web search provider" configured={status.data?.web_search_provider.configured ?? false} />
          </div>
        )}
      </section>

      <section className="settings-section">
        <div className="settings-section-heading"><DatabaseBackup size={20} /><div><h2>一致性备份</h2><p>数据库使用 SQLite online backup 生成；下载副本不是双向同步。</p></div></div>
        <div className="backup-grid">
          <article><DatabaseBackup size={22} /><h3>知识库快照</h3><p>下载通过 integrity check 的单个 SQLite 文件。</p><button className="button button-secondary" onClick={() => backup.mutate()} disabled={backup.isPending}>{backup.isPending ? <RefreshCw className="spin" size={16} /> : <DatabaseBackup size={16} />}生成快照</button>{backupLink && <a className="download-link" href={backupLink.url} download>{backupLink.filename}</a>}</article>
          <article><Archive size={22} /><h3>完整归档</h3><p>包含 kb.sqlite、research tasks 和 manifest.json。</p><button className="button button-secondary" onClick={() => archive.mutate()} disabled={archive.isPending}>{archive.isPending ? <RefreshCw className="spin" size={16} /> : <Archive size={16} />}生成归档</button>{exportLink && <a className="download-link" href={exportLink.url} download>{exportLink.filename}</a>}</article>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-heading"><KeyRound size={20} /><div><h2>CLI / Local Control token</h2><p>新 token 只显示一次。轮换时先创建替代项，再吊销旧项。</p></div></div>
        <form className="token-form" onSubmit={createToken}><label><span className="sr-only">Token 标签</span><input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="例如：MacBook local control" /></label><button className="button button-primary" disabled={issue.isPending}><KeyRound size={16} />创建 token</button></form>
        {issued && (
          <div className="issued-token"><div><strong>请立即保存这个 token</strong><span>关闭后无法再次查看。</span></div><code>{issued.token}</code><button className="button button-secondary" onClick={() => void navigator.clipboard.writeText(issued.token)}><Copy size={15} />复制</button></div>
        )}
        <div className="token-list">
          {tokens.data?.map((token) => (
            <div className={`token-row ${token.revoked_at ? "revoked" : ""}`} key={token.id}>
              <span className="token-icon"><KeyRound size={17} /></span>
              <span><strong>{token.label}</strong><small>创建 {formatDate(token.created_at)} · {token.revoked_at ? `已吊销 ${formatDate(token.revoked_at)}` : `最近使用 ${formatDate(token.last_used_at)}`}</small></span>
              {!token.revoked_at && <button className="icon-button danger" aria-label={`吊销 ${token.label}`} onClick={() => revoke.mutate(token.id)}><Trash2 size={16} /></button>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function ProviderCard({ label, configured }: { label: string; configured: boolean }) {
  return <article className={configured ? "provider-ok" : "provider-missing"}><span>{configured ? <CheckCircle2 size={19} /> : <RefreshCw size={19} />}</span><div><strong>{label}</strong><small>{configured ? "已配置，可用于研究" : "尚未配置"}</small></div></article>;
}
