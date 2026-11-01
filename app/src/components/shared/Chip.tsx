import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** One filter chip; the selected one is tinted. Shared by תנועות and חיסכון. */
export function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-full border px-3 py-1 text-xs tabular-nums",
        selected ? "border-brand bg-brand/15 font-semibold" : "border-line",
      )}
    >
      {children}
    </button>
  );
}

/** A horizontally scrolling row of chips. */
export const CHIP_ROW = "-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5";
