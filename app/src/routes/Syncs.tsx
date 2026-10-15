import { Card, PageTitle, StubNotice } from "@/components/ui";
import { daysSince, num, snapshot, type SourceSync } from "@/lib/data";

const SOURCE_LABEL: Record<string, string> = {
  discount: "דיסקונט — עו״ש",
  "discount-business": "דיסקונט — עסקי",
  "discount-mortgage": "דיסקונט — משכנתא",
  leumi: "לאומי",
  cal: "כאל",
  amex: "אמריקן אקספרס",
  riseup: "RiseUp",
  harel: "הראל",
  more: "מור",
  analyst: "אנליסט",
};

const ENTITY_LABEL: Record<string, string> = {
  transactions: "עסקאות",
  accounts: "חשבונות",
  credit_cards: "כרטיסים",
  loans: "הלוואות",
  savings: "חסכונות",
  income: "הכנסות",
  subscription: "מנוי",
};

/** A scrape counts as stale after a week — same threshold as the header's dot. */
function freshness(days: number): { text: string; cls: string } {
  if (days <= 1) return { text: "עדכני", cls: "pill-good" };
  if (days <= 7) return { text: "לא טרי", cls: "pill-warn" };
  return { text: "ישן", cls: "pill-bad" };
}

function ago(days: number): string {
  if (days === 0) return "היום";
  if (days === 1) return "אתמול";
  return `לפני ${days} ימים`;
}

const dateTime = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const dateOnly = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short", year: "numeric" });

/**
 * A source can be scraped today yet carry nothing recent (the endpoint returned
 * an old window). Flag a newest transaction more than two weeks behind the scrape.
 */
function txnLagDays(s: SourceSync): number | null {
  if (!s.latest_txn_date) return null;
  const lag = Math.floor((new Date(s.last_synced).getTime() - new Date(`${s.latest_txn_date}T12:00:00`).getTime()) / 86_400_000);
  return lag > 14 ? lag : null;
}

function SyncCard({ s }: { s: SourceSync }) {
  const days = daysSince(s.last_synced);
  const f = freshness(days);
  const lag = txnLagDays(s);
  const entities = Object.entries(s.entities).filter(([, n]) => n > 0);

  return (
    <Card>
      <div className="sync-head">
        <div className="card-title" style={{ margin: 0 }}>{SOURCE_LABEL[s.source] ?? s.source}</div>
        <span className={`pill ${f.cls}`}>{f.text}</span>
      </div>
      <div className="kpi-value">{ago(days)}</div>
      <div className="muted sync-meta">{dateTime.format(new Date(s.last_synced))}</div>
      {s.latest_txn_date && (
        <div className="sync-meta">
          עסקה אחרונה: {dateOnly.format(new Date(`${s.latest_txn_date}T12:00:00`))}
          {lag != null && <span className="pill pill-warn sync-lag">פער של {lag} ימים</span>}
        </div>
      )}
      <div className="muted sync-meta">
        {entities.map(([k, n]) => `${num(n)} ${ENTITY_LABEL[k] ?? k}`).join(" · ")}
      </div>
    </Card>
  );
}

export default function Syncs() {
  const syncs = snapshot.syncs ?? [];
  if (!syncs.length) {
    return (
      <div>
        <PageTitle>סנכרונים</PageTitle>
        <StubNotice status="אין נתונים">
          אין עדיין נתוני סנכרון — הריצו <code>python3 data/digest.py</code> ואז sync-data.
        </StubNotice>
      </div>
    );
  }

  // Oldest first: what needs a refresh is what you came here to see.
  const sorted = [...syncs].sort((a, b) => a.last_synced.localeCompare(b.last_synced));
  const stale = sorted.filter((s) => daysSince(s.last_synced) > 7).length;

  return (
    <div>
      <PageTitle>סנכרונים</PageTitle>
      <p className="muted" style={{ marginTop: -8 }}>
        {stale ? `${stale} מקורות לא סונכרנו מעל שבוע.` : "כל המקורות סונכרנו בשבוע האחרון."} הנתונים חושבו{" "}
        {ago(daysSince(snapshot.generated_at))}.
      </p>
      <div className="grid grid-3">
        {sorted.map((s) => (
          <SyncCard key={s.source} s={s} />
        ))}
      </div>
    </div>
  );
}
