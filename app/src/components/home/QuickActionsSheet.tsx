import { Link } from "react-router-dom";
import {
  ArrowLeftRight,
  ChevronLeft,
  Home,
  RefreshCw,
  Target,
  type LucideIcon,
} from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export type QuickAction = "property" | "goal";

function Row({
  icon: Icon,
  title,
  sub,
}: {
  icon: LucideIcon;
  title: string;
  sub: string;
}) {
  return (
    <>
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-secondary text-[var(--lg-primary)]">
        <Icon className="size-5" strokeWidth={1.75} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col text-start">
        <span className="font-medium">{title}</span>
        <span className="truncate text-xs text-muted-foreground">{sub}</span>
      </span>
      <ChevronLeft className="size-4 shrink-0 text-muted-foreground" />
    </>
  );
}

const ROW =
  "flex w-full items-center gap-3 border-b border-line py-3 last:border-b-0 active:bg-panel-2";

/**
 * The band's ＋: the few things worth starting from home (decision 2). Syncing happens per
 * source on /syncs; an offset starts from the expense, so that row opens the spending list.
 */
export default function QuickActionsSheet({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (a: QuickAction) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="bottom"
        dir="rtl"
        className="pb-[calc(env(safe-area-inset-bottom)+12px)]"
      >
        <SheetHeader>
          <SheetTitle className="font-display text-xl font-medium">
            מה עושים?
          </SheetTitle>
          <SheetDescription className="sr-only">פעולות מהירות</SheetDescription>
        </SheetHeader>
        <div className="px-4">
          <Link to="/syncs" className={ROW} onClick={onClose}>
            <Row
              icon={RefreshCw}
              title="סנכרון"
              sub="רענון היתרות מהבנקים והכרטיסים"
            />
          </Link>
          <button
            type="button"
            className={ROW}
            onClick={() => onPick("property")}
          >
            <Row
              icon={Home}
              title="שווי הדירה"
              sub="עדכון ההערכה שנכנסת לשווי הנקי"
            />
          </button>
          <button type="button" className={ROW} onClick={() => onPick("goal")}>
            <Row icon={Target} title="יעד חדש" sub="סכום, תאריך ואופק" />
          </button>
          <Link to="/transactions" className={ROW} onClick={onClose}>
            <Row
              icon={ArrowLeftRight}
              title="קיזוז החזר"
              sub="בחרו את ההוצאה שההחזר מכסה"
            />
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
}
