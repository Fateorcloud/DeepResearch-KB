import { AlertCircle, Inbox } from "lucide-react";

export function LoadingState({ label = "正在加载…" }: { label?: string }) {
  return <div className="state-box" aria-busy="true"><span className="spinner" />{label}</div>;
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="state-box state-column">
      <Inbox size={24} />
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return <div className="alert alert-error"><AlertCircle size={18} />{message}</div>;
}
