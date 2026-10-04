import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { routes } from "./routes";
import { cashflow, daysSince } from "./lib/data";

export default function App() {
  const stale = daysSince(cashflow.generated_at) > 7;
  return (
    <div className="layout">
      <aside className="rail">
        <div className="brand">Plangram</div>
        <nav>
          {routes.map((r) => (
            <NavLink
              key={r.path}
              to={r.path}
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
            >
              {r.label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          עודכן לפני {daysSince(cashflow.generated_at)} ימים
          {stale && <span className="stale-dot" title="נתונים ישנים" />}
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          {routes.map((r) => (
            <Route key={r.path} path={r.path} element={<r.Component />} />
          ))}
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Routes>
      </main>
    </div>
  );
}
