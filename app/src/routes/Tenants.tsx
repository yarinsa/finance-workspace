import { useEffect, useState, type FormEvent } from "react";
import { Card, CardLabel, Page } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/api";
import { MASTER_TENANT_ID, type Me } from "@/lib/tenant";
import {
  createTenant, groupCommand, listTenants, removeMember, setMember, setStatus, syncAccess, tenantUuid,
  type AdminTenant, type TenantRole,
} from "@/lib/tenantAdmin";

const ROLE_LABEL: Record<TenantRole, string> = { OWNER: "בעלים", ADMIN: "מנהל", MEMBER: "חבר" };

/** A membership change whose Cognito group still has to follow (grant after an add, revoke after a remove). */
interface Pending {
  tenantId: string; // GraphQL global id
  email: string;
  kind: "grant" | "revoke";
}
const pendingKey = (p: Pending) => `${p.tenantId}|${p.email}`;

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "הפעולה נכשלה";
}

/** One tenant: its status, its members, and a form to add one. */
function TenantCard({ t, onChange, onPending }: { t: AdminTenant; onChange: (t: AdminTenant) => void; onPending: (p: Pending) => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TenantRole>("MEMBER");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const master = tenantUuid(t.id) === MASTER_TENANT_ID;

  async function run(fn: () => Promise<AdminTenant>, pending?: Pending) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
      if (pending) onPending(pending);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  function add(e: FormEvent) {
    e.preventDefault();
    const address = email.trim().toLowerCase();
    if (!address) return;
    void run(() => setMember(t.id, address, role), { tenantId: t.id, email: address, kind: "grant" }).then(() => setEmail(""));
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{t.name}</div>
          <div className="text-xs text-muted-foreground" dir="ltr">{t.slug}{master ? " · master" : ""}</div>
        </div>
        <span className={`pill ${t.status === "ACTIVE" ? "pill-good" : "pill-warn"}`}>
          {t.status === "ACTIVE" ? "פעיל" : "מושעה"}
        </span>
      </div>

      <ul className="mt-3 flex flex-col gap-1.5">
        {t.members.map((m) => (
          <li key={m.email} className="flex items-center justify-between gap-2 text-sm">
            <span className="min-w-0 truncate" dir="ltr">{m.email}</span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-muted-foreground">{ROLE_LABEL[m.role]}</span>
              <Button
                type="button" variant="ghost" size="sm" disabled={busy}
                onClick={() => void run(() => removeMember(t.id, m.email), { tenantId: t.id, email: m.email, kind: "revoke" })}
              >
                הסרה
              </Button>
            </span>
          </li>
        ))}
      </ul>

      <form onSubmit={add} className="mt-3 flex flex-wrap items-center gap-2">
        <Input
          type="email" dir="ltr" placeholder="email@example.com" value={email}
          onChange={(e) => setEmail(e.target.value)} className="min-w-40 flex-1"
        />
        <select
          value={role} onChange={(e) => setRole(e.target.value as TenantRole)}
          className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
        >
          {(Object.keys(ROLE_LABEL) as TenantRole[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
        <Button type="submit" size="sm" disabled={busy || !email.trim()}>הוספה</Button>
      </form>

      {!master && (
        <div className="mt-3">
          <Button
            type="button" variant="outline" size="sm" disabled={busy}
            onClick={() => void run(() => setStatus(t.id, t.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE"))}
          >
            {t.status === "ACTIVE" ? "השעיה" : "הפעלה מחדש"}
          </Button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
    </Card>
  );
}

/** One membership change waiting for its Cognito group, with the button that applies it. */
function PendingRow({ p, tenant, onDone }: { p: Pending; tenant: AdminTenant | undefined; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      await syncAccess(p.tenantId, p.email);
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="min-w-0">
          <span className="block truncate" dir="ltr">{p.email}</span>
          <span className="text-xs text-muted-foreground">{tenant?.name ?? "—"}</span>
        </span>
        <Button type="button" size="sm" disabled={busy} onClick={() => void apply()}>
          {busy ? "מבצע…" : p.kind === "grant" ? "הענקת גישה" : "ביטול גישה"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-bad">
          {error}
          <br />
          <span className="text-muted-foreground">אפשר גם ידנית: </span>
          <code dir="ltr">{groupCommand({ id: p.tenantId }, p.email).replace(" add ", p.kind === "grant" ? " add " : " remove ")}</code>
        </p>
      )}
    </li>
  );
}

/**
 * Tenant management, for the platform admin only (the API refuses anyone else; this screen also
 * hides itself). The registry changes here are immediate; a member sees a tenant's published files
 * only after the Mac adds them to its Cognito group, so each change shows the command to run.
 */
export default function Tenants() {
  const [admin, setAdmin] = useState<boolean | null>(null);
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<Me>("GET", "/me")
      .then((me) => {
        setAdmin(me.platform_admin);
        return me.platform_admin ? listTenants().then(setTenants) : undefined;
      })
      .catch((e) => {
        setAdmin(false);
        setError(errorText(e));
      });
  }, []);

  const replace = (t: AdminTenant) => setTenants((all) => all.map((x) => (x.id === t.id ? t : x)));
  const addPending = (p: Pending) =>
    setPending((all) => [p, ...all.filter((x) => pendingKey(x) !== pendingKey(p))]);
  const donePending = (p: Pending) => setPending((all) => all.filter((x) => pendingKey(x) !== pendingKey(p)));

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const t = await createTenant(slug.trim(), name.trim(), owner.trim().toLowerCase());
      setTenants((all) => [...all, t]);
      addPending({ tenantId: t.id, email: owner.trim().toLowerCase(), kind: "grant" });
      setSlug(""); setName(""); setOwner("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (admin === null) return <Page title="ניהול משקי בית"><p className="text-sm text-muted-foreground">טוען…</p></Page>;
  if (!admin) return <Page title="ניהול משקי בית"><p className="text-sm text-muted-foreground">אין הרשאה לניהול משקי בית.</p></Page>;

  return (
    <Page title="ניהול משקי בית">
      <Card>
        <CardLabel>משק בית חדש</CardLabel>
        <form onSubmit={create} className="mt-2 flex flex-col gap-2">
          <Input dir="ltr" placeholder="slug (a-z, 0-9, -)" value={slug} onChange={(e) => setSlug(e.target.value)} />
          <Input placeholder="שם" value={name} onChange={(e) => setName(e.target.value)} />
          <Input type="email" dir="ltr" placeholder="אימייל הבעלים" value={owner} onChange={(e) => setOwner(e.target.value)} />
          <div>
            <Button type="submit" size="sm" disabled={busy || !slug.trim() || !name.trim() || !owner.trim()}>יצירה</Button>
          </div>
        </form>
        {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      </Card>

      {pending.length > 0 && (
        <Card>
          <CardLabel>גישה לנתונים</CardLabel>
          <p className="mt-1 text-xs text-muted-foreground">
            חבר רואה את נתוני המשק רק אחרי שהוא נוסף לקבוצת ה-Cognito שלו (ואז הוא מתחבר מחדש). הכפתור מבצע זאת דרך ה-Mac.
          </p>
          <ul className="mt-2 flex flex-col gap-2">
            {pending.map((p) => (
              <PendingRow key={pendingKey(p)} p={p} tenant={tenants.find((t) => t.id === p.tenantId)} onDone={() => donePending(p)} />
            ))}
          </ul>
        </Card>
      )}

      {tenants.map((t) => <TenantCard key={t.id} t={t} onChange={replace} onPending={addPending} />)}
    </Page>
  );
}
