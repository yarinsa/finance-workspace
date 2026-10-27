import { useEffect, useId, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronLeft, Plus } from "lucide-react";
import { Money } from "@/components/common";
import { cn } from "@/lib/utils";
import { getDataVersion, shekel, snapshot, useDataVersion, type Loan } from "@/lib/data";
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

const ACCOUNT_KIND: Record<string, string> = { checking: "עו״ש", business_checking: "עו״ש" };

const INSTITUTION: Record<string, string> = {
  discount: "דיסקונט",
  "discount-business": "דיסקונט עסקי",
  leumi: "לאומי",
  harel: "הראל",
  more: "מור",
  analyst: "אנליסט",
};

/** The query param that opens the savings card (the savings lens's הרחב, old /portfolio links). */
const HOLDINGS_PARAM = "holdings";

/**
 * A home card that opens in place to the things its total is made of. With `param`, it also
 * opens by itself, scrolled into view, when the URL carries `?<param>=1`.
 */
function CollapsibleCard({
  label,
  sub,
  value,
  param,
  children,
}: {
  label: string;
  sub?: string;
  value: number;
  param?: string;
  children: React.ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const asked = param != null && params.get(param) === "1";
  const [open, setOpen] = useState(asked);
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!asked || !param) return;
    setOpen(true);
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    // Consumed: a second link to the same URL opens it again.
    setParams((p) => { p.delete(param); return p; }, { replace: true });
  }, [asked, param, setParams]);

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
          <span className="truncate text-[17px] font-medium">{label}</span>
          {sub && <span className="truncate text-xs text-muted-foreground">{sub}</span>}
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
          <div className="mx-5 border-t border-line pb-2">{children}</div>
        </div>
      </div>
    </div>
  );
}

function Group({ title, children }: { title: string | null; children: React.ReactNode }) {
  return (
    <>
      {title ? <div className="pt-3 pb-1 text-xs font-medium text-muted-foreground">{title}</div> : <div className="pt-1" />}
      {children}
    </>
  );
}

function Line({ title, sub, value }: { title: string; sub: (string | null | undefined | false)[]; value: number }) {
  const meta = sub.filter(Boolean).join(" · ");
  return (
    <div className="flex items-center gap-3 py-2">
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[15px]">{title}</span>
        {meta && <span className="truncate text-xs text-muted-foreground">{meta}</span>}
      </span>
      <span className={cn("font-display text-[17px] font-medium tabular-nums", value < 0 && "text-bad")}>
        <Money>{shekel(value)}</Money>
      </span>
    </div>
  );
}

/**
 * מזומן ופיקדון נזיל: the bank accounts (each with its overdraft line when it has one) and the
 * deposits that can be withdrawn today. Opened, it links on to the balance forecast.
 */
function CashCard({ value }: { value: number }) {
  const accounts = [...(snapshot.bank_accounts ?? [])].sort((a, b) => b.balance - a.balance);
  const deposits = (snapshot.savings ?? []).filter((s) => s.liquid);
  return (
    <CollapsibleCard label="מזומן ופיקדון נזיל" value={value}>
      <Group title="חשבונות בנק">
        {accounts.map((a) => (
          <Line
            key={`${a.institution}-${a.account_id}`}
            title={INSTITUTION[a.institution] ?? a.institution}
            sub={[
              ACCOUNT_KIND[a.kind] ?? a.kind,
              /\d/.test(a.account_id) && a.account_id,
              a.overdraft_limit ? `מסגרת ${shekel(a.overdraft_limit)}` : null,
            ]}
            value={a.balance}
          />
        ))}
      </Group>
      <Group title="פיקדונות נזילים">
        {deposits.length ? (
          deposits.map((d) => (
            <Line key={`${d.institution}-${d.label}`} title={d.label} sub={[INSTITUTION[d.institution] ?? d.institution]} value={d.balance} />
          ))
        ) : (
          <div className="py-2 text-sm text-muted-foreground">אין כרגע פיקדון נזיל.</div>
        )}
      </Group>
      <Link
        to="/monthly?view=forecast"
        className="mt-1 flex items-center justify-between border-t border-line py-3 text-sm font-medium text-[var(--lg-primary)]"
      >
        תחזית היתרה עד המשכורת
        <ChevronLeft className="size-4" />
      </Link>
    </CollapsibleCard>
  );
}

const LENDER: Record<string, string> = { "Bank Discount": "דיסקונט", "Bank Leumi": "לאומי" };

/** "08/2053" from Discount's '20530810' or Leumi's '2028-12-02'. */
function untilMonth(final?: string): string | null {
  const d = (final ?? "").replace(/\D/g, "");
  return d.length >= 6 ? `עד ${d.slice(4, 6)}/${d.slice(0, 4)}` : null;
}

/** Bank names carry RTL/LTR marks and stray spaces ("\u200fללא ריבית הצטרפות \u200f \u200e2529-1/3\u200e"). */
function cleanName(name?: string): string {
  return (name ?? "").replace(/[\u200e\u200f]/g, "").replace(/\s+/g, " ").trim();
}

/**
 * A loan's title. Discount's names are the product's full description ("הלואה לא צמודה
 * ר.קבועה - דיור מתווה"), too long for a phone, so they are rebuilt from the loan's terms;
 * a name the household would recognise (Leumi's "ללא ריבית הצטרפות 2529-1/3") is kept.
 */
function loanTitle(l: Loan): string {
  const name = cleanName(l.name);
  if (!/^הלו?ואה/.test(name)) return name;
  const rate = (l.rate_pct ?? 0) < 0.01 ? "ללא ריבית" : l.rate_type === "fixed" ? "ריבית קבועה" : "ריבית משתנה";
  return [l.index_linked ? "צמודת מדד" : "לא צמודה", rate, name.includes("מתווה") && "מתווה"].filter(Boolean).join(" · ");
}

/**
 * הלוואות / משכנתא: one line per loan or mortgage track, largest first, with what it costs a
 * month and when it ends. Leumi's unread remainder (its summary total minus the loans it
 * lists) has no schedule, so it says so. No rates: a refunded-interest loan would look costly.
 */
function DebtCard({ label, category, total }: { label: string; category: "consumer" | "mortgage"; total: number }) {
  const loans = snapshot.loans.filter((l) => l.category === category).sort((a, b) => (b.balance ?? 0) - (a.balance ?? 0));
  const monthly = loans.reduce((n, l) => n + (l.monthly_payment ?? 0), 0);
  return (
    <CollapsibleCard label={label} sub={monthly ? `${shekel(monthly)} בחודש` : undefined} value={-total}>
      <Group title={category === "mortgage" ? "מסלולים" : null}>
        {loans.map((l) => (
          <Line
            key={`${l.lender}-${String(l.loan_id)}`}
            title={loanTitle(l) || label}
            sub={
              l.monthly_payment
                ? [category === "consumer" && (LENDER[l.lender ?? ""] ?? l.lender), `${shekel(l.monthly_payment)} בחודש`, untilMonth(l.final_date)]
                : [LENDER[l.lender ?? ""] ?? l.lender, "הבנק מדווח רק את היתרה"]
            }
            value={-(l.balance ?? 0)}
          />
        ))}
      </Group>
      <Link
        to="/networth"
        className="mt-1 flex items-center justify-between border-t border-line py-3 text-sm font-medium text-[var(--lg-primary)]"
      >
        {category === "mortgage" ? "המשכנתא לאורך זמן" : "החובות לאורך זמן"}
        <ChevronLeft className="size-4" />
      </Link>
    </CollapsibleCard>
  );
}

/** חיסכון ארוך טווח: the locked funds (a liquid deposit counts as cash, above). */
function SavingsCard({ value }: { value: number }) {
  const holdings = (snapshot.savings ?? []).filter((s) => !s.liquid).sort((a, b) => b.balance - a.balance);
  return (
    <CollapsibleCard label="חיסכון ארוך טווח" sub="פנסיה, השתלמות וגמל" value={value} param={HOLDINGS_PARAM}>
      <Group title="החזקות">
        {holdings.map((h) => (
          <Line
            key={`${h.institution}-${h.kind}-${h.label}`}
            title={KIND[h.kind] ?? h.label}
            sub={[INSTITUTION[h.institution] ?? h.institution, h.work_state, (h.policies_count ?? 0) > 1 && `${h.policies_count} פוליסות`]}
            value={h.balance}
          />
        ))}
      </Group>
    </CollapsibleCard>
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
      <CashCard value={t.bank_balances_sum + (t.liquid_savings ?? 0)} />
      <AccountCard to="/monthly" label="כרטיסי אשראי" sub="החיוב הבא" value={-t.credit_card_debt} />
      <SavingsCard value={t.long_term_savings ?? 0} />
      <DebtCard label="הלוואות" category="consumer" total={t.consumer_loan_balance} />
      <DebtCard label="משכנתא" category="mortgage" total={t.mortgage_balance} />
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
