import { useEffect, useId, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronLeft, Plus } from "lucide-react";
import { Money } from "@/components/common";
import { cn } from "@/lib/utils";
import { getDataVersion, shekel, snapshot, useDataVersion } from "@/lib/data";
import { shownProperty, usePropertyOverlay } from "@/lib/propertyOverlay";

const ROW = "flex w-full items-center gap-3 px-5 py-4 text-inherit no-underline transition duration-200 active:bg-panel-2";
const CARD = `surface ${ROW} active:scale-[.99]`;

function Value({ n }: { n: number }) {
  return (
    <strong className={cn("font-display text-[22px] font-semibold tabular-nums", n < 0 && "text-bad")}>
      <Money>{shekel(n)}</Money>
    </strong>
  );
}

function AccountCard({ to, label, sub, value }: { to: string; label: string; sub?: string; value: number }) {
  return (
    <Link to={to} className={CARD}>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[17px] font-medium">{label}</span>
        {sub && <span className="truncate text-xs text-muted-foreground">{sub}</span>}
      </span>
      <Value n={value} />
      <ChevronLeft className="size-4 shrink-0 text-muted-foreground/70" />
    </Link>
  );
}

const KIND: Record<string, string> = {
  pension: "קרן פנסיה",
  study_fund: "קרן השתלמות",
  provident_fund: "קופת גמל",
  savings: "חיסכון",
};

const INSTITUTION: Record<string, string> = { harel: "הראל", more: "מור", analyst: "אנליסט" };

/** The query param that opens the savings card (the savings lens's הרחב, old /portfolio links). */
const HOLDINGS_PARAM = "holdings";

/**
 * חיסכון ארוך טווח, collapsible: the total on the card, the holdings (pension, study and
 * provident funds — the locked ones; a liquid deposit counts as cash above) when opened.
 * Opens by itself, scrolled into view, when the URL carries `?holdings=1`.
 */
function SavingsCard({ value }: { value: number }) {
  const [params, setParams] = useSearchParams();
  const asked = params.get(HOLDINGS_PARAM) === "1";
  const [open, setOpen] = useState(asked);
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  const holdings = (snapshot.savings ?? []).filter((s) => !s.liquid).sort((a, b) => b.balance - a.balance);

  useEffect(() => {
    if (!asked) return;
    setOpen(true);
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    // Consumed: a second הרחב (same URL otherwise) opens it again.
    setParams((p) => { p.delete(HOLDINGS_PARAM); return p; }, { replace: true });
  }, [asked, setParams]);

  return (
    <div ref={ref} className="surface scroll-mt-4 overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={cn(ROW, "rounded-[var(--lg-radius)] text-start")}
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[17px] font-medium">חיסכון ארוך טווח</span>
          <span className="truncate text-xs text-muted-foreground">פנסיה, השתלמות וגמל</span>
        </span>
        <Value n={value} />
        <ChevronDown
          className={cn("size-4 shrink-0 text-muted-foreground/70 transition-transform duration-300 ease-[var(--ease-calm)]", open && "rotate-180")}
        />
      </button>
      <div
        id={id}
        className={cn(
          "grid transition-[grid-template-rows] duration-300 ease-[var(--ease-calm)]",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden" inert={!open}>
          <div className="mx-5 border-t border-line pb-2">
            <div className="pt-3 pb-1 text-xs font-medium text-muted-foreground">החזקות</div>
            {holdings.map((h) => (
              <div key={`${h.institution}-${h.kind}-${h.label}`} className="flex items-center gap-3 py-2">
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-[15px]">{KIND[h.kind] ?? h.label}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {[INSTITUTION[h.institution] ?? h.institution, h.work_state, (h.policies_count ?? 0) > 1 ? `${h.policies_count} פוליסות` : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <span className="font-display text-[17px] font-medium tabular-nums">
                  <Money>{shekel(h.balance)}</Money>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function dmy(iso: string): string {
  return `${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
}

/**
 * The concept's white account cards under the band: one card per kind of money, debts in
 * terracotta, and the apartment, whose value is typed in by hand (tap to enter or revalue).
 */
export default function AccountCards({ onEditProperty }: { onEditProperty: () => void }) {
  const t = snapshot.totals;
  useDataVersion();
  const property = shownProperty(
    (snapshot.assets ?? []).find((a) => a.kind === "property") ?? null,
    usePropertyOverlay(),
    getDataVersion(),
  );
  return (
    <div className="flex flex-col gap-2.5">
      <AccountCard to="/monthly?view=forecast" label="מזומן ופיקדון נזיל" value={t.bank_balances_sum + (t.liquid_savings ?? 0)} />
      <AccountCard to="/monthly" label="כרטיסי אשראי" sub="החיוב הבא" value={-t.credit_card_debt} />
      <SavingsCard value={t.long_term_savings ?? 0} />
      <AccountCard to="/networth" label="הלוואות" value={-t.consumer_loan_balance} />
      <AccountCard to="/networth" label="משכנתא" value={-t.mortgage_balance} />
      <button type="button" onClick={onEditProperty} className={cn(CARD, "text-start")}>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[17px] font-medium">{property?.label ?? "נכס (דירה)"}</span>
          <span className="truncate text-xs text-muted-foreground">
            {property ? (property.pending ? "נשמר · השווי הנקי מתעדכן…" : `עודכן ידנית ${dmy(property.valued_at)}`) : "הערכה ידנית לשווי הנקי"}
          </span>
        </span>
        {property ? (
          <Value n={property.value} />
        ) : (
          <span className="flex items-center gap-1 rounded-full border border-[color:var(--lg-secondary-line)] bg-secondary px-3 py-1 text-sm font-medium">
            <Plus className="size-4" /> הוספה
          </span>
        )}
        <ChevronLeft className="size-4 shrink-0 text-muted-foreground/70" />
      </button>
    </div>
  );
}
