import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bell, ChevronLeft, EllipsisVertical, Plus } from "lucide-react";
import { Money } from "@/components/common";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { cashflow, daysSince, shekel, snapshot } from "@/lib/data";
import { useInboxCount } from "@/lib/inbox";
import { cashLens, defaultLens, LENS_KEY, spendLens, type Lens, type LensKey } from "@/lib/lenses";
import LensChart from "./LensChart";
import Signal from "./Signal";

function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/** The lenses this build has data for, in tab order. Net worth, savings and debt join in Phase 3. */
function buildLenses(): Lens[] {
  return [spendLens(cashflow.pace), cashLens(cashflow.history, cashflow.runway)].filter((l): l is Lens => l != null);
}

function freshness(): string {
  const d = daysSince(cashflow.generated_at);
  return d <= 0 ? "עודכן היום" : d === 1 ? "עודכן אתמול" : `עודכן לפני ${d} ימים`;
}

const ROUND = "grid size-10 place-items-center rounded-full bg-[color-mix(in_srgb,var(--hero-text)_14%,transparent)] text-[var(--hero-text)] transition duration-200 active:scale-95";

/**
 * The home band (docs/home-redesign.md): a teal hero holding one lens at a time. Swipe or tap
 * a tab to change lens; the lens lives in the URL (`?lens=cash`). Each lens shows its big
 * number, a change chip only when both ends are measured, and a chart ending at היום.
 */
export default function HomeBand({ onQuickActions }: { onQuickActions: () => void }) {
  const lenses = useMemo(buildLenses, []);
  const keys = lenses.map((l) => l.key);
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get("lens") as LensKey | null;
  const [pinned, setPinned] = useState(() => storage()?.getItem(LENS_KEY) ?? null);
  const initial = fromUrl && keys.includes(fromUrl) ? fromUrl : defaultLens(keys, snapshot.totals, pinned);
  const [active, setActive] = useState<LensKey>(initial);
  const track = useRef<HTMLDivElement>(null);
  const inbox = useInboxCount();

  const scrollTo = useCallback(
    (key: LensKey, smooth: boolean) => {
      const el = track.current;
      const i = keys.indexOf(key);
      if (!el || i < 0) return;
      // RTL: the first slide is rightmost and scrollLeft runs negative from 0.
      el.scrollTo({ left: -i * el.clientWidth, behavior: smooth ? "smooth" : "auto" });
    },
    [keys],
  );

  useLayoutEffect(() => scrollTo(initial, false), []); // eslint-disable-line react-hooks/exhaustive-deps

  const select = (key: LensKey, smooth = true) => {
    setActive(key);
    scrollTo(key, smooth);
    setParams((p) => {
      p.set("lens", key);
      return p;
    }, { replace: true });
  };

  const onScroll = () => {
    const el = track.current;
    if (!el) return;
    const i = Math.round(Math.abs(el.scrollLeft) / el.clientWidth);
    const key = keys[i];
    if (key && key !== active) {
      setActive(key);
      setParams((p) => {
        p.set("lens", key);
        return p;
      }, { replace: true });
    }
  };

  const pin = (key: LensKey | null) => {
    setPinned(key);
    if (key) storage()?.setItem(LENS_KEY, key);
    else storage()?.removeItem(LENS_KEY);
  };

  const current = lenses.find((l) => l.key === active) ?? lenses[0];
  if (!current) return null;

  return (
    <section
      aria-label="תמונת מצב"
      className="relative -mx-4 -mt-4 overflow-hidden px-4 pt-[calc(env(safe-area-inset-top)+12px)] pb-14 text-[var(--hero-text)] md:mx-0 md:mt-0 md:rounded-[var(--lg-radius)] md:pt-6"
      style={{ background: "var(--hero-bg)" }}
    >
      <header className="flex items-start justify-between gap-3">
        <Signal pace={cashflow.pace} runway={cashflow.runway} />
        <div className="flex items-center gap-2">
          <Link to="/inbox" aria-label={inbox ? `אינבוקס, ${inbox} פריטים` : "אינבוקס"} className={cn(ROUND, "relative")}>
            <Bell className="size-5" strokeWidth={1.75} />
            {inbox > 0 && <span className="absolute top-2 end-2.5 size-2 rounded-full bg-[var(--hero-alert)] ring-2 ring-[var(--holst-2)]" />}
          </Link>
          <button type="button" aria-label="פעולות מהירות" onClick={onQuickActions} className={ROUND}>
            <Plus className="size-5" strokeWidth={1.75} />
          </button>
        </div>
      </header>

      <div role="tablist" aria-label="עדשות" className="mt-5 flex gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {lenses.map((l) => (
          <button
            key={l.key}
            type="button"
            role="tab"
            aria-selected={l.key === active}
            onClick={() => select(l.key)}
            className={cn(
              "shrink-0 rounded-full px-4 py-1.5 text-[15px] transition-colors duration-200",
              l.key === active
                ? "bg-[color-mix(in_srgb,var(--hero-text)_16%,transparent)] font-semibold"
                : "text-[var(--hero-muted)]",
            )}
          >
            {l.label}
          </button>
        ))}
      </div>

      <div
        ref={track}
        onScroll={onScroll}
        className="-mx-4 mt-4 flex snap-x snap-mandatory overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {lenses.map((l) => (
          <div key={l.key} className="w-full shrink-0 snap-start px-4" aria-hidden={l.key !== active}>
            <div className="font-display text-[48px] leading-[1.1] font-medium tabular-nums md:text-[56px]">
              <Money>{shekel(l.value)}</Money>
            </div>
            <div className="mt-2 flex min-h-7 flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              {l.delta && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[color-mix(in_srgb,var(--hero-text)_14%,transparent)] px-3 py-1 font-medium tabular-nums">
                  <span aria-hidden>{l.delta.amount >= 0 ? "↑" : "↓"}</span>
                  <Money>{shekel(Math.abs(l.delta.amount))}</Money> {l.delta.text}
                </span>
              )}
              <span className="text-[var(--hero-muted)]">{freshness()}</span>
            </div>
            <div className="mt-3">
              <LensChart lens={l} />
            </div>
            {l.note && <div className="mt-1 text-xs text-[var(--hero-muted)]">{l.note}</div>}
          </div>
        ))}
      </div>

      <footer className="mt-3 flex items-center justify-between">
        <Link to={current.to} className="inline-flex items-center gap-1 text-[15px] font-medium text-[var(--hero-text)] underline underline-offset-4">
          הרחב <ChevronLeft className="size-4" />
        </Link>
        <div className="flex items-center gap-2" aria-hidden>
          {lenses.map((l) => (
            <span
              key={l.key}
              className={cn(
                "size-1.5 rounded-full transition-colors duration-200",
                l.key === active ? "bg-[var(--hero-text)]" : "bg-[color-mix(in_srgb,var(--hero-text)_35%,transparent)]",
              )}
            />
          ))}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger aria-label="אפשרויות" className="grid size-8 place-items-center rounded-full text-[var(--hero-text)]">
            <EllipsisVertical className="size-5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {pinned === current.key ? (
              <DropdownMenuItem onSelect={() => pin(null)}>לפתוח לפי ברירת המחדל</DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={() => pin(current.key)}>לפתוח תמיד ב{current.label}</DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <Link to={current.to}>לפרטים המלאים</Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </footer>
    </section>
  );
}
