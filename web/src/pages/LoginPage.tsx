import { useState, type FormEvent } from "react";
import { BookOpenText, LockKeyhole } from "lucide-react";
import { ApiError, login } from "../api";
import type { Session } from "../types";

export default function LoginPage({ onLogin }: { onLogin: (session: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      onLogin(await login(username, password));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "无法连接研究服务");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-intro">
        <div className="brand-mark large"><BookOpenText size={27} /></div>
        <p className="eyebrow">PRIVATE RESEARCH WORKSPACE</p>
        <h1>把已有知识与外部研究，放进同一条证据链。</h1>
        <p>管理长期知识、运行真实 Research，并检查每条结论的来源、路径与版本。</p>
      </section>
      <section className="login-card" aria-labelledby="login-title">
        <LockKeyhole size={22} />
        <h2 id="login-title">登录工作台</h2>
        <p className="muted">此实例仅开放给管理员，不提供注册入口。</p>
        <form onSubmit={submit}>
          <label>
            用户名
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
          </label>
          <label>
            密码
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          {error && <div className="alert alert-error">{error}</div>}
          <button className="button button-primary button-block" disabled={submitting}>
            {submitting ? "正在验证…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
