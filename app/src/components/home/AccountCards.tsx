import { Link } from "react-router-dom";
import { ChevronLeft, Plus } from "lucide-react";
import { Money } from "@/components/common";
import { cn } from "@/lib/utils";
import { getDataVersion, shekel, snapshot, useDataVersion } from "@/lib/data";
import { shownProperty, usePropertyOverlay } from "@/lib/propertyOverlay";

const CARD =
  "surface flex w-full items-center gap-3 px-5 py-4 text-inherit no-underline transition duration-200 active:scale-[.99] active:bg-panel-2";

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
      <AccountCard to="/portfolio" label="חיסכון ארוך טווח" sub="פנסיה, השתלמות וגמל" value={t.long_term_savings ?? 0} />
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
