import { createContext, useContext, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Info } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
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
  const inner = (
    <div
      className={cn(
        "h-full rounded-[20px] border border-line bg-panel p-4 shadow-[var(--shadow)] transition md:p-[18px]",
        to && "group-hover:border-brand group-active:scale-[.98] group-active:border-brand",
        className,
      )}
    >
      {children}
    </div>
  );
  return to ? (
    <Link to={to} className="group block [-webkit-tap-highlight-color:transparent]">
      {inner}
    </Link>
  ) : (
    inner
  );
}

/** Heading level for card titles: h2 on a page, h3 once inside a `Section`. */
const HeadingLevel = createContext<2 | 3>(2);

/** Small muted heading at the top of a card (h2, or h3 inside a `Section`). */
export function CardLabel({ children }: { children: ReactNode }) {
  const Tag = useContext(HeadingLevel) === 3 ? "h3" : "h2";
  return <Tag className="m-0 mb-2.5 text-sm font-semibold text-muted-foreground">{children}</Tag>;
}

/** Headline figure; `tone` colours it by sign or verdict. */
export function BigNumber({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: "good" | "bad";
}) {
  return (
    <div
      className={cn(
        "text-[28px] leading-tight font-extrabold tabular-nums md:text-[34px]",
        tone === "good" && "text-good",
        tone === "bad" && "text-bad",
      )}
    >
      {children}
    </div>
  );
}

/** Label / value line inside a card; consecutive rows get a divider. */
export function StatRow({
  label,
  value,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: "good" | "bad";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line py-2 last:border-b-0">
      <span>{label}</span>
      <strong
        className={cn("tabular-nums", tone === "good" && "text-good", tone === "bad" && "text-bad")}
      >
        {value}
      </strong>
    </div>
  );
}

/** Label + value with a proportional bar underneath (`fraction` in 0–1). */
export function BarRow({
  label,
  value,
  fraction,
}: {
  label: ReactNode;
  value: ReactNode;
  fraction: number;
}) {
  return (
    <div className="py-2">
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="truncate">{label}</span>
        <strong className="shrink-0 tabular-nums">{value}</strong>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-panel-2">
        <div
          className="h-full rounded-full bg-brand"
          style={{ width: `${Math.max(0, Math.min(1, fraction)) * 100}%` }}
        />
      </div>
    </div>
  );
}

/** Amber call-to-action strip (e.g. "time to refresh balances"). */
export function Nudge({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 rounded-[14px] border border-warn/30 bg-warn/8 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between">
      <span>{children}</span>
      {action && (
        <span className="self-start rounded-[10px] bg-brand px-3.5 py-2 font-bold text-[#0b0e14] sm:self-auto">
          {action}
        </span>
      )}
    </div>
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

/**
 * A KPI tile: label, big value, optional verdict pill and hint.
 * The hint opens in a Popover so it works on touch (a `title=` never shows on phones);
 * taps on it (and inside the portaled content) don't follow the surrounding Card link.
 * Pass `compactValue` to swap in a short form (₪1.6M) when the tile is too narrow.
 */
export function Kpi({
  label,
  value,
  compactValue,
  rank = null,
  hint,
}: {
  label: string;
  value: ReactNode;
  compactValue?: ReactNode;
  rank?: Rank;
  hint?: string;
}) {
  const [hintOpen, setHintOpen] = useState(false);
  return (
    <div className="@container flex h-full flex-col items-start gap-1.5">
      <div className="flex w-full items-start justify-between gap-2 text-[13px] text-muted-foreground">
        <span>{label}</span>
        {hint && (
          <Popover open={hintOpen} onOpenChange={setHintOpen}>
            <PopoverTrigger
              aria-label={`הסבר: ${label}`}
              className="-m-2 shrink-0 p-2 text-muted-foreground/70"
              onClick={(e) => {
                // Inside a Card link: don't navigate, toggle ourselves
                // (Radix skips its own toggle once default is prevented).
                e.preventDefault();
                e.stopPropagation();
                setHintOpen((o) => !o);
              }}
            >
              <Info className="size-4" />
            </PopoverTrigger>
            <PopoverContent
              className="w-72 text-sm leading-relaxed"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            >
              {hint}
            </PopoverContent>
          </Popover>
        )}
      </div>
      <div className="text-[22px] font-extrabold tabular-nums">
        {compactValue != null ? (
          <>
            <span className="@max-[7.5rem]:hidden">{value}</span>
            <span className="hidden @max-[7.5rem]:inline" aria-hidden>
              {compactValue}
            </span>
          </>
        ) : (
          value
        )}
      </div>
      <RankPill rank={rank} />
    </div>
  );
}

/**
 * Responsive grid for KPI cards: 2-up on phones, `cols` from `md`.
 * A lone last tile on phones spans the full row instead of leaving a hole.
 */
export function KpiGrid({ cols = 4, children }: { cols?: 3 | 4 | 5; children: ReactNode }) {
  const md = { 3: "md:grid-cols-3", 4: "md:grid-cols-4", 5: "md:grid-cols-5" }[cols];
  return (
    <div
      className={`grid grid-cols-2 gap-3 md:gap-3.5 ${md} max-md:[&>*:last-child:nth-child(odd)]:col-span-2`}
    >
      {children}
    </div>
  );
}

/** Page heading. On phones the sticky header already names the page, so it's visually hidden there. */
export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="text-[26px] font-extrabold max-md:sr-only">{children}</h1>;
}

/**
 * Root of every page: one vertical rhythm for its direct children (cards, sections).
 * Narrow (phone-shaped, 720px) by default; `wide` for pages whose content is multi-column at md.
 */
export function Page({
  title,
  wide,
  children,
}: {
  title?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-4 md:gap-[18px]", !wide && "max-w-[720px]")}>
      {title && <PageTitle>{title}</PageTitle>}
      {children}
    </div>
  );
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

/** A titled block of a page, with an optional "see all" deep link or custom `action`. */
export function Section({
  title,
  to,
  linkLabel = "הכל",
  action,
  children,
}: {
  title: ReactNode;
  to?: string;
  linkLabel?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mt-3 first:mt-0 [h1+&]:mt-0">
      <header className="mb-2.5 flex items-baseline justify-between">
        <h2 className="m-0 text-lg font-extrabold">{title}</h2>
        {action}
        {to && (
          <Link to={to} className="text-sm font-semibold text-brand no-underline">
            {linkLabel} ›
          </Link>
        )}
      </header>
      <HeadingLevel.Provider value={3}>{children}</HeadingLevel.Provider>
    </section>
  );
}

/** One line in a list card: label (+ optional sub-label), value, optional share bar (0–1). */
export function ListRow({
  label,
  sub,
  value,
  share,
}: {
  label: ReactNode;
  sub?: ReactNode;
  value: ReactNode;
  share?: number;
}) {
  return (
    <div className="border-b border-line py-2.5 last:border-b-0 [&:has(+.list-foot)]:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <span>{label}</span>
          {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
        </div>
        <strong className="whitespace-nowrap tabular-nums">{value}</strong>
      </div>
      {share != null && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-panel-2">
          <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(share * 100, 1)}%` }} />
        </div>
      )}
    </div>
  );
}
