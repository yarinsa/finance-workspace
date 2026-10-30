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
const STEP_LABEL: Record<string, string> = {
  invited: "הוזמן במייל",
  added: "נוסף לגישה",
  removed: "הגישה בוטלה",
  disabled: "החשבון הושבת",
  unchanged: "ללא שינוי",
};

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "הפעולה נכשלה";
}

/** One person whose Cognito account or group has to follow a membership change. */
interface Access {
  tenantId: string; // GraphQL global id
  email: string;
  state: "running" | "failed";
  error?: string;
}
const accessKey = (a: Pick<Access, "tenantId" | "email">) => `${a.tenantId}|${a.email}`;

/** One tenant: its status, its members, and a form to add one. */
function TenantCard({
  t, onChange, provision,
}: {
  t: AdminTenant;
  onChange: (t: AdminTenant) => void;
  provision: (tenantId: string, email: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TenantRole>("MEMBER");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const master = tenantUuid(t.id) === MASTER_TENANT_ID;

  /** Change the registry, then (when `follow` lists people) provision or deprovision them in Cognito. */
  async function run(fn: () => Promise<AdminTenant>, follow: string[] = []) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
      return;
    }
    setBusy(false);
    for (const who of follow) await provision(t.id, who);
  }

  function add(e: FormEvent) {
    e.preventDefault();
    const address = email.trim().toLowerCase();
    if (!address) return;
    setEmail("");
    void run(() => setMember(t.id, address, role), [address]);
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
                onClick={() => void run(() => removeMember(t.id, m.email), [m.email])}
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
            onClick={() =>
              void run(() => setStatus(t.id, t.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE"), t.members.map((m) => m.email))
            }
          >
            {t.status === "ACTIVE" ? "השעיה" : "הפעלה מחדש"}
          </Button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
    </Card>
  );
}

/**
 * Tenant management, for the platform admin only (the API refuses anyone else; this screen also
 * hides itself). Every membership change is followed by a Cognito sync on the Mac (the API has no
 * AWS credentials): a new member is invited by email and put in the tenant's group, a removed one
 * is taken out, and an account with no access left is disabled. A sync that fails stays in the
 * list with a retry button and the manual command.
 */
export default function Tenants() {
  const [admin, setAdmin] = useState<boolean | null>(null);
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [access, setAccess] = useState<Access[]>([]);
  const [done, setDone] = useState<string[]>([]);
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
  const upsert = (a: Access) =>
    setAccess((all) => [a, ...all.filter((x) => accessKey(x) !== accessKey(a))]);

  /** Sync one person's Cognito state with the database; a failure stays listed to retry. */
  async function provision(tenantId: string, email: string) {
    upsert({ tenantId, email, state: "running" });
    try {
      const steps = (await syncAccess(tenantId, email)).split(",").map((s) => STEP_LABEL[s] ?? s);
      setAccess((all) => all.filter((x) => accessKey(x) !== accessKey({ tenantId, email })));
      setDone((d) => [`${email} — ${steps.join(" · ")}`, ...d].slice(0, 5));
    } catch (e) {
      upsert({ tenantId, email, state: "failed", error: errorText(e) });
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const ownerEmail = owner.trim().toLowerCase();
    try {
      const t = await createTenant(slug.trim(), name.trim(), ownerEmail);
      setTenants((all) => [...all, t]);
      setSlug(""); setName(""); setOwner("");
      setBusy(false);
      await provision(t.id, ownerEmail);
    } catch (err) {
      setError(errorText(err));
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

      {(access.length > 0 || done.length > 0) && (
        <Card>
          <CardLabel>חשבונות וגישה</CardLabel>
          <p className="mt-1 text-xs text-muted-foreground">
            כל שינוי בחברים מעדכן את חשבון ה-Cognito דרך ה-Mac: חבר חדש מוזמן במייל, מי שהוסר מאבד גישה,
            וחשבון בלי אף משק פעיל מושבת.
          </p>
          <ul className="mt-2 flex flex-col gap-2">
            {done.map((d) => <li key={d} className="text-sm text-good" dir="auto">✓ {d}</li>)}
            {access.map((a) => (
              <li key={accessKey(a)} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate" dir="ltr">{a.email}</span>
                    <span className="text-xs text-muted-foreground">
                      {tenants.find((t) => t.id === a.tenantId)?.name ?? "—"}
                    </span>
                  </span>
                  {a.state === "running" ? (
                    <span className="text-xs text-muted-foreground">מעדכן…</span>
                  ) : (
                    <Button type="button" size="sm" onClick={() => void provision(a.tenantId, a.email)}>נסה שוב</Button>
                  )}
                </div>
                {a.state === "failed" && (
                  <p role="alert" className="text-xs text-bad">
                    {a.error}
                    <br />
                    <span className="text-muted-foreground">ידנית: </span>
                    <code dir="ltr">{groupCommand({ id: a.tenantId }, a.email)}</code>
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tenants.map((t) => <TenantCard key={t.id} t={t} onChange={replace} provision={provision} />)}
    </Page>
  );
}
