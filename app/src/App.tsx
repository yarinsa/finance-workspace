import { useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { routes } from "./routes";
import { cashflow, daysSince } from "./lib/data";
import { CashflowIcon, GoalIcon, HomeIcon, MoreIcon, WalletIcon } from "./components/icons";

/** Paths pinned to the mobile tab bar; the rest live behind "עוד". */
const TAB_PATHS = ["/overview", "/cashflow", "/goals", "/networth"];
const TAB_ICON: Record<string, () => JSX.Element> = {
  "/overview": HomeIcon,
  "/cashflow": CashflowIcon,
  "/goals": GoalIcon,
  "/networth": WalletIcon,
};

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-item active" : "nav-item");

export default function App() {
  const age = daysSince(cashflow.generated_at);
  const stale = age > 7;
  const [moreOpen, setMoreOpen] = useState(false);
  const { pathname } = useLocation();
  const tabs = routes.filter((r) => TAB_PATHS.includes(r.path));
  const more = routes.filter((r) => !TAB_PATHS.includes(r.path));
  const inMore = more.some((r) => r.path === pathname);
  const current = routes.find((r) => r.path === pathname);

  return (
    <div className="layout">
      <aside className="rail">
        <nav>
          {routes.map((r) => (
            <NavLink key={r.path} to={r.path} className={navClass}>
              {r.label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          עודכן לפני {age} ימים
          {stale && <span className="stale-dot" title="נתונים ישנים" />}
        </div>
      </aside>

      <header className="topbar">
        <span className="topbar-title">{current?.label}</span>
        <span className="topbar-age">
          {stale && <span className="stale-dot" title="נתונים ישנים" />}
          עודכן {age === 0 ? "היום" : `לפני ${age} ימים`}
        </span>
      </header>

      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          {routes.map((r) => (
            <Route key={r.path} path={r.path} element={<r.Component />} />
          ))}
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Routes>
      </main>

      {moreOpen && (
        <div className="sheet-backdrop" onClick={() => setMoreOpen(false)}>
          <nav className="sheet" onClick={(e) => e.stopPropagation()}>
            {more.map((r) => (
              <NavLink key={r.path} to={r.path} className={navClass} onClick={() => setMoreOpen(false)}>
                {r.label}
              </NavLink>
            ))}
          </nav>
        </div>
      )}

      <nav className="tabbar">
        {tabs.map((r) => {
          const Icon = TAB_ICON[r.path];
          return (
            <NavLink key={r.path} to={r.path} className={({ isActive }) => (isActive ? "tab active" : "tab")}>
              <Icon />
              <span>{r.label}</span>
            </NavLink>
          );
        })}
        <button className={inMore || moreOpen ? "tab active" : "tab"} onClick={() => setMoreOpen((o) => !o)}>
          <MoreIcon />
          <span>עוד</span>
        </button>
      </nav>
    </div>
  );
}
