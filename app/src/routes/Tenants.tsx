import { useEffect, useState, type FormEvent } from "react";
import { Card, CardLabel, Page } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/api";
import { MASTER_TENANT_ID, type Me } from "@/lib/tenant";
import {
  createTenant, groupCommand, listTenants, removeMember, setMember, setStatus, tenantUuid,
  type AdminTenant, type TenantRole,
} from "@/lib/tenantAdmin";

const ROLE_LABEL: Record<TenantRole, string> = { OWNER: "בעלים", ADMIN: "מנהל", MEMBER: "חבר" };

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "הפעולה נכשלה";
}

/** One tenant: its status, its members, and a form to add one. */
function TenantCard({ t, onChange, onNote }: { t: AdminTenant; onChange: (t: AdminTenant) => void; onNote: (n: string) => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TenantRole>("MEMBER");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const master = tenantUuid(t.id) === MASTER_TENANT_ID;

  async function run(fn: () => Promise<AdminTenant>, note?: string) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
      if (note) onNote(note);
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
    void run(() => setMember(t.id, address, role), groupCommand(t, address)).then(() => setEmail(""));
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
                onClick={() => void run(() => removeMember(t.id, m.email))}
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

/**
 * Tenant management, for the platform admin only (the API refuses anyone else; this screen also
 * hides itself). The registry changes here are immediate; a member sees a tenant's published files
 * only after the Mac adds them to its Cognito group, so each change shows the command to run.
 */
export default function Tenants() {
  const [admin, setAdmin] = useState<boolean | null>(null);
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
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
  const note = (cmd: string) => setNotes((n) => (n.includes(cmd) ? n : [cmd, ...n]));

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const t = await createTenant(slug.trim(), name.trim(), owner.trim().toLowerCase());
      setTenants((all) => [...all, t]);
      note(groupCommand(t, owner.trim().toLowerCase()));
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

      {notes.length > 0 && (
        <Card>
          <CardLabel>להריץ על ה-Mac</CardLabel>
          <p className="mt-1 text-xs text-muted-foreground">
            כדי שהחבר יראה את הנתונים שלו, יש להוסיף אותו לקבוצת ה-Cognito של המשק (ואז להתחבר מחדש):
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {notes.map((c) => <li key={c}><code className="text-xs" dir="ltr">{c}</code></li>)}
          </ul>
        </Card>
      )}

      {tenants.map((t) => <TenantCard key={t.id} t={t} onChange={replace} onNote={note} />)}
    </Page>
  );
}
