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

/** A titled block of the Overview feed, with an optional "see all" deep link. */
export function Section({
  title,
  to,
  linkLabel = "הכל",
  children,
}: {
  title: string;
  to?: string;
  linkLabel?: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <header className="section-head">
        <h2 className="section-title">{title}</h2>
        {to && (
          <Link to={to} className="section-link">
            {linkLabel} ›
          </Link>
        )}
      </header>
      {children}
    </section>
  );
}

/** One line in a list card: label (+ optional sub-label) and a right-aligned value. */
export function ListRow({
  label,
  sub,
  value,
  share,
}: {
  label: ReactNode;
  sub?: ReactNode;
  value: ReactNode;
  /** 0–1: draws a thin proportion bar under the row. */
  share?: number;
}) {
  return (
    <div className="list-row">
      <div className="list-row-main">
        <div className="list-row-text">
          <span>{label}</span>
          {sub && <span className="list-row-sub">{sub}</span>}
        </div>
        <strong className="list-row-value">{value}</strong>
      </div>
      {share != null && (
        <div className="bar-track thin">
          <div className="bar-fill" style={{ width: `${Math.max(share * 100, 1)}%` }} />
        </div>
      )}
    </div>
  );
}
