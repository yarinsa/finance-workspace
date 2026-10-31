import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  loadSourceSecrets,
  secretStatus,
  setSourceSecret,
  type SecretField,
  type SourceSecrets as View,
} from "@/lib/sourceSecrets";
import { useLedgerApi } from "@/lib/useLedgerApi";

/**
 * A source's connection fields as the household's vault holds them: set or missing, and a way to
 * replace one. A value is typed here, sent once and cleared; it is never shown again (no reveal).
 * When this household is not on the vault with a write identity, `fallback` (the read-only
 * form that points at `.env`) is shown instead.
 */
export default function SourceSecrets({ source, fallback }: { source: string; fallback: React.ReactNode }) {
  const { online } = useLedgerApi();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (online === false) return;
    let live = true;
    loadSourceSecrets(source)
      .then((v) => live && setView(v))
      .catch(() => live && setError("לא הצלחנו לטעון את פרטי החיבור."));
    return () => {
      live = false;
    };
  }, [source, online]);

  if (online === false) return <>{fallback}</>;
  if (error)
    return (
      <>
        <p role="status" className="secret-note text-warn">{error}</p>
        {fallback}
      </>
    );
  if (!view) return <p role="status" className="secret-note text-muted-foreground">טוען…</p>;
  if (!view.canEdit) return <>{fallback}</>;
  return (
    <ul className="secret-fields">
      {view.fields.map((f) => (
        <SecretRow key={f.name} source={source} field={f} onSaved={setView} />
      ))}
    </ul>
  );
}

function SecretRow({ source, field, onSaved }: { source: string; field: SecretField; onSaved: (v: View) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      onSaved(await setSourceSecret(source, field.name, value));
      setValue("");
      setEditing(false);
    } catch (err) {
      setError("השמירה לא הצליחה. אפשר לנסות שוב.");
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    setEditing(false);
    setValue("");
    setError(null);
  }

  return (
    <li className="secret-row">
      <div className="secret-head">
        <span className="secret-title">{field.title}</span>
        <span className={field.isSet ? "secret-status text-muted-foreground" : "secret-status text-warn"}>
          {secretStatus(field)}
        </span>
        {!editing && (
          <Button type="button" size="sm" variant="outline" onClick={() => setEditing(true)} aria-label={`${field.isSet ? "החלף" : "הגדר"} ${field.title}`}>
            {field.isSet ? "החלף" : "הגדר"}
          </Button>
        )}
      </div>
      {editing && (
        <form onSubmit={save} className="secret-edit">
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            type={field.masked ? "password" : "text"}
            autoComplete="off"
            aria-label={field.title}
            dir="ltr"
            className="min-w-0 flex-1"
            spellCheck={false}
            autoCapitalize="off"
            onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), cancel())}
            autoFocus
          />
          <Button type="submit" size="sm" disabled={busy || !value}>
            {busy ? "שומר…" : "שמור"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={cancel}
          >
            ביטול
          </Button>
        </form>
      )}
      {error && <p role="status" className="text-xs text-warn">{error}</p>}
    </li>
  );
}
