import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { snoozeUntil, type Notification, type SnoozeChoice } from "@/lib/notifications";

const CHOICES: { key: SnoozeChoice; label: string }[] = [
  { key: "tomorrow", label: "מחר" },
  { key: "week", label: "שבוע" },
  { key: "payday", label: "אחרי המשכורת" },
];

/** Bottom sheet that hides an item until tomorrow, next week or payday. */
export default function SnoozeSheet({
  target,
  payday,
  onPick,
  onClose,
}: {
  target: Notification | null;
  /** ISO date of the next payday (cashflow.runway.next_payday); a week from now when unknown. */
  payday: string | null;
  onPick: (n: Notification, until: string) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open={target != null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" dir="rtl" className="pb-[env(safe-area-inset-bottom)]">
        <SheetHeader>
          <SheetTitle>השהה עד…</SheetTitle>
          <SheetDescription className="line-clamp-2">{target?.title}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-2 px-4 pb-4">
          {CHOICES.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className="rounded-2xl border border-line bg-panel px-4 py-3 text-start font-semibold active:scale-[.98]"
              onClick={() => target && onPick(target, snoozeUntil(key, new Date(), payday))}
            >
              {label}
            </button>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
