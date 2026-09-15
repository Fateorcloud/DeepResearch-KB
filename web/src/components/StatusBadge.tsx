import type { TaskStatus } from "../types";

const labels: Record<TaskStatus, string> = {
  queued: "等待中",
  running: "研究中",
  completed: "已完成",
  failed: "失败",
};

export default function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>;
}
