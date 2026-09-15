import type { ReactNode } from "react";
import {
  BookOpenText,
  Database,
  Home,
  LogOut,
  Settings,
} from "lucide-react";
import { NavLink } from "react-router-dom";

interface Props {
  username: string;
  onLogout: () => Promise<void>;
  children: ReactNode;
}

export default function AppShell({ username, onLogout, children }: Props) {
  return (
    <div className="app-frame">
      <header className="topbar">
        <NavLink to="/" className="brand" aria-label="DeepResearch-KB 首页">
          <span className="brand-mark"><BookOpenText size={18} /></span>
          <span>DeepResearch-KB</span>
        </NavLink>
        <nav className="main-nav" aria-label="主导航">
          <NavLink to="/" end><Home size={17} />研究</NavLink>
          <NavLink to="/knowledge"><Database size={17} />知识库</NavLink>
          <NavLink to="/settings"><Settings size={17} />设置</NavLink>
        </nav>
        <div className="account-menu">
          <span className="account-name">{username}</span>
          <button className="icon-button" type="button" onClick={() => void onLogout()} aria-label="退出登录">
            <LogOut size={17} />
          </button>
        </div>
      </header>
      <main className="page-shell">{children}</main>
    </div>
  );
}
