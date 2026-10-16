import { Card, CardLabel } from "@/components/common";
import { shekel } from "@/lib/data";
import type { SpendingMonth } from "@/lib/spending";

const ROWS: { key: keyof SpendingMonth["excluded"]; label: string; hint: string }[] = [
  { key: "card_bills", label: "חיובי כרטיס אשראי", hint: "הקניות עצמן כבר נספרו" },
  { key: "transfers", label: "העברות בין החשבונות שלכם", hint: "כסף שרק עובר ממקום למקום" },
  { key: "savings", label: "חיסכון והפקדות", hint: "נחסך, לא הוצא" },
  { key: "income", label: "הכנסות והחזרים", hint: "כסף שנכנס" },
];

/** "Excluded from spending" (Monzo) — what the month total deliberately leaves out. */
export default function ExcludedSpendingCard({ excluded }: { excluded: SpendingMonth["excluded"] }) {
  const rows = ROWS.filter((r) => excluded[r.key].count > 0);
  return (
    <Card>
      <CardLabel>לא נספר כהוצאה</CardLabel>
      {rows.length === 0 ? (
        <div className="text-sm text-muted-foreground">אין תנועות שהוחרגו החודש.</div>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((r) => (
            <li key={r.key} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate">{r.label}</div>
                <div className="text-xs text-muted-foreground">
                  {r.hint} · {excluded[r.key].count} תנועות
                </div>
              </div>
              <strong className="shrink-0 tabular-nums">{shekel(excluded[r.key].amount)}</strong>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
