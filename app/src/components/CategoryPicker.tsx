import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

/**
 * A searchable category list: full-width tappable rows (recently used first, then every
 * category), a check on the current one, and a "new category" row when the search matches
 * nothing exactly. Used inside the swipe sheet and by `CategoryPickerSheet`.
 */
export function CategoryList({
  categories,
  current,
  recent = [],
  disabled,
  onPick,
}: {
  categories: string[];
  current?: string | null;
  recent?: string[];
  disabled?: boolean;
  onPick: (category: string) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().slice(0, 64);
  const matches = (c: string) => !q || c.includes(q);
  const recentShown = q ? [] : recent.filter((c) => categories.includes(c) || c === current);
  const all = categories.filter(matches);
  const canCreate = q && !categories.includes(q);

  return (
    <div>
      <div className="sticky top-0 z-10 bg-background pb-2">
        <Input
          value={query}
          disabled={disabled}
          maxLength={64}
          placeholder="חיפוש או קטגוריה חדשה"
          aria-label="חיפוש קטגוריה"
          className="h-11 text-base"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter" || !q) return;
            e.preventDefault();
            onPick(all.length === 1 && !canCreate ? all[0] : q);
          }}
        />
      </div>

      {canCreate && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onPick(q)}
          className="mb-2 flex min-h-11 w-full items-center gap-2 rounded-lg border border-dashed border-line px-3 text-start text-sm disabled:opacity-40"
        >
          <span className="text-brand">+</span> קטגוריה חדשה: <span className="font-semibold">{q}</span>
        </button>
      )}

      {recentShown.length > 0 && (
        <Section title="בשימוש לאחרונה" items={recentShown} current={current} disabled={disabled} onPick={onPick} />
      )}
      {all.length > 0 ? (
        <Section title={q ? "תוצאות" : "כל הקטגוריות"} items={all} current={current} disabled={disabled} onPick={onPick} />
      ) : (
        !canCreate && <div className="py-6 text-center text-sm text-muted-foreground">אין קטגוריות</div>
      )}
    </div>
  );
}

function Section({
  title,
  items,
  current,
  disabled,
  onPick,
}: {
  title: string;
  items: string[];
  current?: string | null;
  disabled?: boolean;
  onPick: (category: string) => void;
}) {
  return (
    <div className="mb-3">
      <span className="mb-1 block text-xs text-muted-foreground">{title}</span>
      <ul role="listbox" aria-label={title} className="divide-y divide-line overflow-hidden rounded-xl border border-line">
        {items.map((c) => (
          <li key={c}>
            <button
              type="button"
              role="option"
              aria-selected={c === current}
              disabled={disabled}
              onClick={() => onPick(c)}
              className={`flex min-h-11 w-full items-center justify-between px-3 text-start text-[15px] active:bg-muted disabled:opacity-40 ${
                c === current ? "bg-brand/10 font-semibold" : ""
              }`}
            >
              <span className="truncate">{c}</span>
              {c === current && <span className="text-brand" aria-hidden>✓</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** `CategoryList` in its own bottom sheet, for picking a category from inside another form. */
export function CategoryPickerSheet({
  open,
  onClose,
  ...list
}: { open: boolean; onClose: () => void } & Parameters<typeof CategoryList>[0]) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="max-h-[85dvh] overflow-y-auto" dir="rtl">
        <SheetHeader>
          <SheetTitle className="text-lg font-bold">בחירת קטגוריה</SheetTitle>
        </SheetHeader>
        <div className="px-4 pb-4">
          {open && (
            <CategoryList
              {...list}
              onPick={(c) => {
                list.onPick(c);
                onClose();
              }}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
