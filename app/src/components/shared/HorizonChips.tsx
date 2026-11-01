import { HORIZON_LABEL, HORIZON_SHORT } from "@/components/TransactionEditSheet";
import type { Horizon } from "@/lib/api";

/**
 * The three horizon chips as a radio group. `onPick` gets the tapped horizon (the caller decides
 * that tapping the active one clears it). Read-only (`editable` false) shows only the active chip.
 */
export function HorizonChips({
  value,
  editable,
  busy,
  onPick,
}: {
  value: Horizon | null;
  editable: boolean;
  busy?: boolean;
  onPick: (h: Horizon) => void;
}) {
  return (
    <div className="flex gap-1.5" role="radiogroup" aria-label="אופק">
      {(Object.keys(HORIZON_SHORT) as Horizon[]).map((h) =>
        editable || busy || h === value ? (
          <button
            key={h}
            type="button"
            role="radio"
            aria-checked={value === h}
            title={HORIZON_LABEL[h]}
            disabled={!editable}
            onClick={() => onPick(h)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${
              value === h ? "border-brand bg-brand/15 font-semibold" : "border-line text-muted-foreground"
            }`}
          >
            {HORIZON_SHORT[h]}
          </button>
        ) : null,
      )}
    </div>
  );
}
