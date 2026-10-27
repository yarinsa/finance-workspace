import { Check, X } from "lucide-react";
import { dismissToast, useToast } from "@/lib/toast";

/**
 * The kit's "✓ Changes saved." card: a forest check circle, one line, an optional "בטל".
 * Sits above the bottom tab bar on phones; announced politely to screen readers.
 */
export function Toaster() {
  const t = useToast();
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 z-50 flex justify-center px-4"
      style={{ bottom: "calc(var(--tabbar-total) + 12px)" }}
    >
      {t && (
        <div
          key={t.id}
          role="status"
          className="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-[18px] border border-[color:var(--card-border)] bg-panel px-4 py-3 shadow-[var(--shadow)] animate-in fade-in slide-in-from-bottom-2 duration-300"
        >
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[var(--lg-primary)] text-[var(--lg-on-accent)]">
            <Check className="size-4" strokeWidth={2.5} />
          </span>
          <span className="flex-1 text-[15px]">{t.text}</span>
          {t.undo && (
            <button
              type="button"
              onClick={() => {
                t.undo?.();
                dismissToast();
              }}
              className="text-sm font-semibold text-brand"
            >
              בטל
            </button>
          )}
          <button type="button" onClick={dismissToast} aria-label="סגירה" className="text-muted-foreground">
            <X className="size-4" />
          </button>
        </div>
      )}
    </div>
  );
}
