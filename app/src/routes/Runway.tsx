import { BigNumber, Card, CardLabel, Page, Section } from "@/components/common";
import { RunwayAlerts, RunwayChart } from "@/components/RunwayChart";
import { cashflow, shekel, shekelSigned, type Runway as RunwayData } from "@/lib/data";

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short" }).format(new Date(`${iso.slice(0, 10)}T12:00:00`));

const KIND_LABEL: Record<RunwayData["events"][number]["kind"], string> = {
  income: "הכנסה",
  loan: "הלוואה",
  card: "אשראי",
  housing: "דיור",
  bill: "חשבון",
};

/** Hero: how much can be spent before payday, or how short the account is. */
function Hero({ r }: { r: RunwayData }) {
  const safe = r.safe_to_spend;
  const over = r.headroom_to_limit != null && r.headroom_to_limit < 0;
  const ok = safe != null && safe > 0;
  return (
    <Card>
      <CardLabel>כמה אפשר להוציא</CardLabel>
      {safe == null ? (
        <BigNumber>—</BigNumber>
      ) : ok ? (
        <>
          <BigNumber tone="good">{shekel(safe)} פנוי עד המשכורת</BigNumber>
          {r.safe_per_day != null && r.days_to_payday != null && (
            <div className="mt-1 text-sm text-muted-foreground">
              {shekel(r.safe_per_day)} ליום · {r.days_to_payday} ימים
            </div>
          )}
        </>
      ) : (
        <>
          <BigNumber tone="bad">חסרים {shekel(-safe)} עד המשכורת</BigNumber>
          {r.headroom_to_limit != null && (
            <div className={`mt-1 text-sm font-semibold ${over ? "text-bad" : "text-warn"}`}>
              {over ? `חריגה מהמסגרת: ${shekel(-r.headroom_to_limit)}` : `מרווח עד סוף המסגרת: ${shekel(r.headroom_to_limit)}`}
            </div>
          )}
        </>
      )}
      <div className="mt-2 text-xs text-muted-foreground">
        {r.next_payday && `משכורת ${shortDate(r.next_payday.date)} · ${shekel(r.next_payday.amount)} · `}
        נכון ל-{shortDate(r.as_of)} · יתרה {shekel(r.start_balance)}
      </div>
    </Card>
  );
}

function EventRow({ e, limit }: { e: RunwayData["events"][number]; limit: number }) {
  const breach = e.balance_after < -Math.abs(limit);
  return (
    <div className="flex items-center gap-3 border-b border-line py-2.5 last:border-b-0">
      <span className="w-12 shrink-0 text-sm text-muted-foreground tabular-nums">{shortDate(e.date)}</span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{e.name}</span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="rounded-full bg-panel-2 px-2 py-0.5">{KIND_LABEL[e.kind] ?? e.kind}</span>
          {e.confidence === "inferred" && <span>משוער</span>}
        </span>
      </div>
      <div className="flex shrink-0 flex-col items-end">
        <strong className={`tabular-nums ${e.amount > 0 ? "text-good" : ""}`}>{shekelSigned(e.amount)}</strong>
        <span className={`text-xs tabular-nums ${breach ? "font-semibold text-bad" : "text-muted-foreground"}`}>
          {shekel(e.balance_after)}
        </span>
      </div>
    </div>
  );
}

export default function Runway() {
  const r = cashflow.runway;
  if (!r) {
    return (
      <Page title="יתרה צפויה">
        <p className="muted">אין עדיין תחזית יתרה — הריצו את הפייפליין לעדכון.</p>
      </Page>
    );
  }
  const buffer = r.liquid_buffer.reduce((a, b) => a + b.balance, 0);
  return (
    <Page title="יתרה צפויה">
      <Hero r={r} />

      <Section title="מסלול היתרה">
        <Card>
          <RunwayChart r={r} />
        </Card>
      </Section>

      <RunwayAlerts r={r} />

      {r.events.length > 0 && (
        <Section title="תנועות קרובות">
          <Card>
            {r.events.map((e, i) => (
              <EventRow key={`${e.date}-${e.name}-${i}`} e={e} limit={r.overdraft_limit} />
            ))}
          </Card>
        </Section>
      )}

      {buffer > 0 && (
        <Card className="text-muted-foreground">
          יש {shekel(buffer)} בפיקדון נזיל — אפשר לכסות מכאן
        </Card>
      )}

      <p className="text-xs leading-relaxed text-muted-foreground">
        התחזית כוללת הוצאות קבועות בלבד (ללא הוצאות יומיומיות); חיובי האשראי מוערכים לפי החודש הקודם.
      </p>
    </Page>
  );
}
