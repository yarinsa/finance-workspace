import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { Section } from "@/components/common";
import { cn } from "@/lib/utils";
import { shekel, snapshot } from "@/lib/data";

function Row({ to, label, value, muted }: { to: string; label: string; value: number | null; muted?: boolean }) {
  return (
    <Link
      to={to}
      className={cn(
        "flex items-center gap-2 border-b border-line px-4 py-3 text-inherit no-underline last:border-b-0 active:bg-panel-2",
        muted && "text-muted-foreground",
      )}
    >
      <span className="flex-1 truncate">{label}</span>
      <strong className={cn("tabular-nums", value != null && value < 0 && !muted && "text-bad")}>
        {value != null ? shekel(value) : "—"}
      </strong>
      <ChevronLeft className="size-4 shrink-0 text-muted-foreground/60" />
    </Link>
  );
}

/** Mint-style one-line account rows plus the net-worth footer (apartment excluded). */
export default function AccountRows({ netWorth }: { netWorth: number | null }) {
  const t = snapshot.totals;
  return (
    <Section title="חשבונות" to="/networth">
      <div className="overflow-hidden surface">
        <Row to="/monthly?view=forecast" label="מזומן ופיקדון נזיל" value={t.bank_balances_sum + (t.liquid_savings ?? 0)} />
        <Row to="/monthly" label="כרטיסי אשראי" value={-t.credit_card_debt} />
        <Row to="/networth" label="הלוואות" value={-t.consumer_loan_balance} />
        <Row to="/networth" label="משכנתא" value={-t.mortgage_balance} />
        <Row to="/portfolio" label="חיסכון ארוך טווח" value={t.long_term_savings ?? 0} />
        <Row to="/networth" label="שווי נקי (ללא הדירה)" value={netWorth} muted />
      </div>
    </Section>
  );
}
