import { useEffect, useState, type FormEvent } from "react";
import { Card, CardLabel, Page, StubNotice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, startLogin, submitOtp } from "@/lib/api";
import { currentSubscription, disablePush, enablePush, pushState, readPushEnv, type PushState } from "@/lib/push";
import { daysSince, snapshot, type SourceSync } from "@/lib/data";
import {
  displayState,
  isRunning,
  needsAttention,
  OTP_SOURCES,
  STATE_PILL,
  useSyncStatus,
  type Display,
  type SourceStatus,
  type SyncState,
} from "@/lib/syncStatus";
import { useLedgerApi } from "@/lib/useLedgerApi";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  discount: "דיסקונט — עו״ש",
  "discount-business": "דיסקונט — עסקי",
  "discount-mortgage": "דיסקונט — משכנתא",
  leumi: "לאומי",
  cal: "כאל",
  amex: "אמריקן אקספרס",
  max: "מקס",
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
  subscription: "מנויים",
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

const num = new Intl.NumberFormat("he-IL");
const dateTime = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const dateOnly = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short", year: "numeric" });
const timeOnly = new Intl.DateTimeFormat("he-IL", { hour: "2-digit", minute: "2-digit" });

const txDate = (d: string) => dateOnly.format(new Date(`${d}T12:00:00`));

/**
 * A source can be scraped today yet carry nothing recent (the endpoint returned
 * an old window). Flag a newest transaction more than two weeks behind the scrape.
 */
function txnLagDays(s: SourceSync): number | null {
  if (!s.latest_txn_date) return null;
  const lag = Math.floor((new Date(s.last_synced).getTime() - new Date(`${s.latest_txn_date}T12:00:00`).getTime()) / 86_400_000);
  return lag > 14 ? lag : null;
}

/** A live entry this much older than the newest run belongs to a source no longer synced automatically. */
const DROPPED_AFTER_MS = 24 * 60 * 60_000;

/** One source on the page: its scraped data (snapshot) and/or its automated sync (live). */
interface Item {
  source: string;
  data?: SourceSync;
  live?: SourceStatus;
  display?: Display;
}

/** Needs you first, then running, then the oldest data: what you came here to see. */
function rank(it: Item): number {
  if (it.display && needsAttention(it.display)) return 0;
  if (it.display && isRunning(it.display)) return 1;
  return 2;
}

/** Timeline mark per step: done steps are ticks, the step a run ended on carries its outcome. */
const STEP_MARK: Record<"ok" | "run" | "bad" | "warn", { icon: string; cls: string }> = {
  ok: { icon: "✓", cls: "text-good" },
  run: { icon: "•", cls: "text-brand" },
  bad: { icon: "✕", cls: "text-bad" },
  warn: { icon: "!", cls: "text-warn" },
};

function stepMark(status: SyncState, last: boolean, running: boolean): (typeof STEP_MARK)["ok"] {
  if (status === "failed" || status === "rejected" || status === "needs_login") return STEP_MARK.bad;
  if (status === "waiting_for_login" || status === "waiting_for_otp") return STEP_MARK.warn;
  if (last && running) return STEP_MARK.run;
  return STEP_MARK.ok;
}

/** Collapsed-row line for a finished run: this source's own intake, not the ledger total. */
function intakeLine(live: SourceStatus): string | null {
  const after = live.records;
  if (!after) return null;
  const tx = after.transactions;
  const before = live.records_before?.transactions;
  if (tx == null) {
    return Object.entries(after)
      .map(([e, n]) => `${num.format(n)} ${ENTITY_LABEL[e] ?? e}`)
      .join(" · ");
  }
  const delta = before != null ? tx - before : 0;
  return `${delta > 0 ? `+${num.format(delta)} חדשות` : "אין עסקאות חדשות"} · ${num.format(tx)} עסקאות`;
}

/** "+38 עסקאות חדשות · סה״כ 360" from the dump gate's before/after counts. */
function Intake({ live }: { live: SourceStatus }) {
  const after = live.records;
  if (!after) return null;
  const before = live.records_before ?? {};
  const tx = after.transactions;
  const delta = tx != null && before.transactions != null ? tx - before.transactions : null;
  const others = Object.entries(after).filter(([e]) => e !== "transactions");
  return (
    <div className="sync-intake">
      {tx != null && (
        <strong className="tabular-nums">
          {delta == null
            ? `${num.format(tx)} עסקאות`
            : delta > 0
              ? `+${num.format(delta)} עסקאות חדשות`
              : delta < 0
                ? `${num.format(Math.abs(delta))} עסקאות פחות מהסנכרון הקודם`
                : "אין עסקאות חדשות"}
        </strong>
      )}
      <span className="text-xs text-muted-foreground">
        {[
          tx != null && delta != null && `סה״כ ${num.format(tx)} עסקאות`,
          ...others.map(([e, n]) => `${num.format(n)} ${ENTITY_LABEL[e] ?? e}`),
          live.latest_txn && `עסקה אחרונה ${txDate(live.latest_txn)}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </span>
    </div>
  );
}

function Timeline({ live, running }: { live: SourceStatus; running: boolean }) {
  const log = live.log ?? [];
  if (!log.length) return null;
  return (
    <ol className="sync-timeline">
      {log.map((step, i) => {
        const mark = stepMark(step.status, i === log.length - 1, running);
        return (
          <li key={`${step.status}-${i}`}>
            <span className={cn("sync-step-icon", mark.cls)} aria-hidden>
              {mark.icon}
            </span>
            <span>{STATE_PILL[step.status].text}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{timeOnly.format(new Date(step.at))}</span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Log in to an OTP source (Harel) from here: start a one-source sync on the Mac, which sends the
 * SMS, then type the code. The code goes straight to the waiting login and is never stored.
 * Needs the ledger API (Mac on); scheduled runs never send a code on their own.
 */
function OtpLogin({ source, display }: { source: string; display?: Display }) {
  const { online } = useLedgerApi();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<"login" | "code" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const waiting = display === "waiting_for_otp";
  if (display && isRunning(display) && !waiting) return null;

  async function act(fn: () => Promise<unknown>, done: "login" | "code") {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setSent(done);
      if (done === "code") setCode("");
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "not_waiting"
          ? "ההתחברות כבר לא ממתינה לקוד — התחל מחדש"
          : e instanceof ApiError
            ? e.message || "הפעולה נכשלה"
            : "המק לא זמין כרגע",
      );
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (/^\d{4,8}$/.test(code)) void act(() => submitOtp(source, code), "code");
  }

  if (online === false) return <p className="text-xs text-muted-foreground">התחברות מהאפליקציה זמינה כשהמק פועל.</p>;

  return (
    <div className="sync-otp">
      {waiting && sent !== "code" ? (
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="קוד מה-SMS"
            aria-label="קוד אימות"
            dir="ltr"
            className="w-36 text-center tabular-nums tracking-widest"
            autoFocus
          />
          <Button type="submit" size="sm" disabled={busy || code.length < 4}>
            שלח קוד
          </Button>
        </form>
      ) : waiting ? (
        <p className="text-xs text-muted-foreground">הקוד נשלח — מתחבר…</p>
      ) : (
        <Button size="sm" variant="outline" disabled={busy || sent === "login"} onClick={() => void act(() => startLogin(source), "login")}>
          {sent === "login" ? "שולח SMS…" : "התחבר עם קוד SMS"}
        </Button>
      )}
      {error && <p className="text-xs text-bad">{error}</p>}
    </div>
  );
}

const PUSH_HINT: Record<PushState, string> = {
  unsupported: "הדפדפן הזה לא תומך בהתראות.",
  "ios-install": "הוסף למסך הבית כדי לקבל התראות",
  denied: "ההתראות חסומות — אפשר לאפשר אותן בהגדרות הדפדפן.",
  offline: "הגדרת התראות זמינה כשהמק פועל.",
  off: "התראה כשצריך להתחבר, כשסנכרון נכשל, על פריטים חדשים לטיפול וסיכום יומי ב-22:00.",
  on: "מופעלות במכשיר הזה.",
};

/** Opt this device in or out of the push notifications the Mac sends (finance/push.py). */
function NotificationsCard() {
  const { online } = useLedgerApi();
  const [subscribed, setSubscribed] = useState(false);
  const [permission, setPermission] = useState(readPushEnv().permission);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void currentSubscription().then((sub) => setSubscribed(sub != null));
  }, []);

  const state = pushState({ ...readPushEnv(), permission }, online, subscribed);
  const usable = state === "on" || state === "off";

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (state === "on") {
        await disablePush();
        setSubscribed(false);
      } else {
        const result = await enablePush();
        setSubscribed(result === "on");
      }
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "not_configured"
          ? "ההתראות עוד לא הוגדרו בשרת (מפתחות VAPID)"
          : e instanceof ApiError
            ? e.message || "הפעולה נכשלה"
            : "המק לא זמין כרגע",
      );
    } finally {
      setPermission(readPushEnv().permission);
      setBusy(false);
    }
  }

  return (
    <Card className="mb-3">
      <CardLabel>התראות</CardLabel>
      <div className="flex items-center justify-between gap-3">
        <p className="m-0 text-sm text-muted-foreground">{PUSH_HINT[state]}</p>
        {usable && (
          <Button size="sm" variant={state === "on" ? "outline" : "default"} disabled={busy} onClick={() => void toggle()}>
            {busy ? "רגע…" : state === "on" ? "כבה" : "הפעל"}
          </Button>
        )}
      </div>
      {error && <p className="mt-2 mb-0 text-xs text-bad">{error}</p>}
    </Card>
  );
}

function SyncItem({ it }: { it: Item }) {
  const { data, live, display } = it;
  const days = data ? daysSince(data.last_synced) : null;
  const lag = data ? txnLagDays(data) : null;
  const running = display ? isRunning(display) : false;
  const attention = display ? needsAttention(display) : false;

  // Automated sources show the run's state; manual ones how fresh their dump is.
  const pill = display
    ? STATE_PILL[display]
    : days != null
      ? lag != null && days <= 1
        ? { text: "חסרות עסקאות", cls: "pill-warn" }
        : freshness(days)
      : STATE_PILL.stale;
  const sub = live
    ? display === "stale"
      ? "העדכון האחרון מהסנכרון התקבל מזמן — ייתכן שה-worker נפל"
      : (display === "done" && intakeLine(live)) || live.message
    : data && `${dateTime.format(new Date(data.last_synced))} · ${ago(days ?? 0)}`;
  const pct = live?.step && live.total_steps ? Math.round((live.step / live.total_steps) * 100) : 0;
  const failed = display === "failed" || display === "rejected";

  return (
    <details className="sync-item group/sync" open={attention}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 py-2.5">
        <span className="flex min-w-0 items-center gap-2">
          <span className="text-muted-foreground transition-transform group-open/sync:-rotate-90" aria-hidden>
            ‹
          </span>
          <span className="flex min-w-0 flex-col">
            <span>
              {SOURCE_LABEL[it.source] ?? it.source}
              <span className="sync-mode">{live ? "אוטומטי" : "ידני"}</span>
            </span>
            {sub && <span className="truncate text-xs text-muted-foreground">{sub}</span>}
          </span>
        </span>
        <span className="sync-value shrink-0">
          {running && live?.step != null && `${live.step}/${live.total_steps}`}
          <span className={`pill ${pill.cls}`}>
            {running && <span className="live-pulse" aria-hidden />}
            {pill.text}
          </span>
        </span>
      </summary>

      <div className="sync-body">
        {running && (
          <div className="live-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${pct}%` }} />
          </div>
        )}
        {live?.error && (failed || attention) && (
          <pre className="sync-error" dir="auto">
            {live.error}
          </pre>
        )}
        {OTP_SOURCES.has(it.source) && <OtpLogin key={live?.run_id} source={it.source} display={display} />}
        {live && <Intake live={live} />}
        {live && <Timeline live={live} running={running} />}

        {data && (
          <dl className="sync-facts">
            <dt>נתונים מעודכנים</dt>
            <dd>
              {dateTime.format(new Date(data.last_synced))}
              {lag != null && <span className="sync-lag">פער של {lag} ימים</span>}
            </dd>
            {data.latest_txn_date && (
              <>
                <dt>עסקה אחרונה</dt>
                <dd>{txDate(data.latest_txn_date)}</dd>
              </>
            )}
            {Object.keys(data.entities).length > 0 && (
              <>
                <dt>במקור</dt>
                <dd>
                  {Object.entries(data.entities)
                    .map(([e, n]) => `${num.format(n)} ${ENTITY_LABEL[e] ?? e}`)
                    .join(" · ")}
                </dd>
              </>
            )}
          </dl>
        )}
        {live && (
          <p className="live-meta muted">
            ריצה אחרונה {dateTime.format(new Date(live.started_at))}
            {live.last_success_at
              ? ` · סנכרון מוצלח אחרון ${dateTime.format(new Date(live.last_success_at))}`
              : " · עדיין אין סנכרון מוצלח"}
          </p>
        )}
      </div>
    </details>
  );
}

export default function Syncs() {
  const live = useSyncStatus();
  const syncs = snapshot.syncs ?? [];
  const liveSources = live?.sources ?? {};
  if (!syncs.length && !Object.keys(liveSources).length) {
    return (
      <Page title="סנכרונים">
        <StubNotice status="אין נתונים">
          אין עדיין נתוני סנכרון — הריצו <code>python3 data/digest.py</code> ואז sync-data.
        </StubNotice>
      </Page>
    );
  }

  const bySource = new Map<string, Item>();
  for (const s of syncs) bySource.set(s.source, { source: s.source, data: s });
  // A source the newest run left out (e.g. moved off the schedule) keeps its last entry in
  // sync-status.json; that old "needs login" is not current, so judge it like a manual source.
  const newestRun = Math.max(0, ...Object.values(liveSources).map((s) => new Date(s.started_at).getTime()));
  for (const [source, s] of Object.entries(liveSources)) {
    if (newestRun - new Date(s.started_at).getTime() > DROPPED_AFTER_MS) continue;
    bySource.set(source, { ...(bySource.get(source) ?? { source }), live: s, display: displayState(s) });
  }
  const items = [...bySource.values()].sort(
    (a, b) => rank(a) - rank(b) || (a.data?.last_synced ?? "").localeCompare(b.data?.last_synced ?? ""),
  );
  const stale = syncs.filter((s) => daysSince(s.last_synced) > 7).length;

  return (
    <Page title="סנכרונים">
      <p className="muted">
        {stale ? `${stale} מקורות לא סונכרנו מעל שבוע.` : "כל המקורות סונכרנו בשבוע האחרון."} הנתונים חושבו{" "}
        {ago(daysSince(snapshot.generated_at))}.
      </p>
      <NotificationsCard />
      <Card>
        {items.map((it) => (
          <SyncItem key={it.source} it={it} />
        ))}
      </Card>
    </Page>
  );
}
