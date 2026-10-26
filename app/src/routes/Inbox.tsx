import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Archive, BellOff, Check } from "lucide-react";
import { Card, Page, Section } from "@/components/common";
import NotificationRow from "@/components/inbox/NotificationRow";
import SnoozeSheet from "@/components/inbox/SnoozeSheet";
import { SwipeableRow } from "@/components/SwipeableRow";
import { cashflow } from "@/lib/data";
import { useInbox } from "@/lib/inbox";
import { cn } from "@/lib/utils";
import { inTab, isArchived, isUnread, openItems, parseTab, TABS, type Notification } from "@/lib/notifications";

/** Everything that needs attention, in tabs by category: swipe to archive or snooze, tap to read. */
export default function Inbox() {
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const [showArchived, setShowArchived] = useState(false);
  const [snoozing, setSnoozing] = useState<Notification | null>(null);
  const inbox = useInbox();

  const open = useMemo(() => openItems(inbox.items), [inbox.items]);
  const archived = useMemo(() => inbox.items.filter(isArchived), [inbox.items]);
  const shown = inTab(showArchived ? archived : open, tab);
  const unreadShown = shown.filter(isUnread);

  return (
    <Page title="אינבוקס">
      <div role="tablist" aria-label="קטגוריות" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
        {TABS.map((t) => {
          const count = inTab(open, t.key).length;
          const selected = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setParams(t.key === "all" ? {} : { tab: t.key }, { replace: true })}
              className={cn(
                "shrink-0 rounded-full border px-3.5 py-1.5 text-sm",
                selected ? "border-brand bg-brand/15 font-bold" : "border-line text-muted-foreground",
              )}
            >
              {t.label}
              {count > 0 && <span className="ms-1.5 tabular-nums">{count}</span>}
            </button>
          );
        })}
      </div>

      <Section
        title={showArchived ? "ארכיון" : "פתוחים"}
        action={
          !showArchived && unreadShown.length > 0 ? (
            <button type="button" className="text-sm font-semibold text-brand" onClick={() => inbox.markAllRead(tab, unreadShown)}>
              סמן הכל כנקרא
            </button>
          ) : undefined
        }
      >
        {shown.length === 0 ? (
          <Card>
            <div className="flex items-center gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-good/15 text-good">
                <Check className="size-4" />
              </span>
              <span className="flex-1 font-bold">{showArchived ? "הארכיון ריק" : "האינבוקס ריק ✓"}</span>
            </div>
          </Card>
        ) : (
          <div className="overflow-hidden rounded-[20px] border border-line bg-panel shadow-[var(--shadow)]">
            {shown.map((n) => (
              <div key={n.id} className="border-b border-line last:border-b-0">
                {showArchived ? (
                  <NotificationRow n={n} onRead={inbox.markRead} onRestore={inbox.unarchive} />
                ) : (
                  <SwipeableRow
                    onSwipeLeft={() => inbox.archive(n)}
                    onSwipeRight={() => setSnoozing(n)}
                    leftLabel="ארכיון"
                    rightLabel="השהה"
                    leftIcon={Archive}
                    rightIcon={BellOff}
                    leftClass="bg-sky-600"
                    rightClass="bg-warn"
                  >
                    <NotificationRow n={n} onRead={inbox.markRead} />
                  </SwipeableRow>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {(archived.length > 0 || showArchived) && (
        <button
          type="button"
          className="self-start text-sm font-semibold text-muted-foreground"
          onClick={() => setShowArchived((v) => !v)}
        >
          {showArchived ? "חזרה לאינבוקס" : `ארכיון (${archived.length})`}
        </button>
      )}

      <SnoozeSheet
        target={snoozing}
        payday={cashflow.runway?.next_payday?.date ?? null}
        onPick={(n, until) => {
          inbox.snooze(n, until);
          setSnoozing(null);
        }}
        onClose={() => setSnoozing(null)}
      />
    </Page>
  );
}
