import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Rank } from "@/lib/data";

/** A clickable card that deep-links to its owning feature (Plangram pattern). */
export function Card({
  to,
  children,
  className = "",
}: {
  to?: string;
  children: ReactNode;
  className?: string;
}) {
  const inner = <div className={`card ${className}`}>{children}</div>;
  return to ? (
    <Link to={to} className="card-link">
      {inner}
    </Link>
  ) : (
    inner
  );
}

const RANK_LABEL: Record<string, { text: string; cls: string }> = {
  good: { text: "מעולה", cls: "pill-good" },
  bad: { text: "לא משהו", cls: "pill-bad" },
  warning: { text: "לב לב", cls: "pill-warn" },
};

export function RankPill({ rank }: { rank: Rank }) {
  if (!rank) return null;
  const r = RANK_LABEL[rank];
  if (!r) return null;
  return <span className={`pill ${r.cls}`}>{r.text}</span>;
}

/** A KPI tile: big value, label, optional verdict pill + tooltip. */
export function Kpi({
  label,
  value,
  rank = null,
  hint,
}: {
  label: string;
  value: ReactNode;
  rank?: Rank;
  hint?: string;
}) {
  return (
    <div className="kpi" title={hint}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      <RankPill rank={rank} />
    </div>
  );
}

export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="page-title">{children}</h1>;
}

/** Honest placeholder for screens whose data we don't yet produce. */
export function StubNotice({
  status,
  children,
}: {
  status: string;
  children?: ReactNode;
}) {
  return (
    <div className="stub">
      <span className="stub-badge">{status}</span>
      <div className="stub-body">{children}</div>
    </div>
  );
}
