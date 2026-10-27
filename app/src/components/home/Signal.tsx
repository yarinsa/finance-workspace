import { useState } from "react";
import { Money } from "@/components/common";
import { pct, shekel, type Pace, type Runway } from "@/lib/data";
import { readSignalMode, SIGNAL_KEY, signalValue, type SignalMode } from "@/lib/lenses";

function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;   // private mode: the toggle still works, it just isn't remembered
  }
}

/**
 * The band's corner signal (where the concept shows a credit score): this month's spend as a
 * share of income; a tap flips it to "safe to spend until payday". The choice is remembered on
 * this device.
 */
export default function Signal({ pace, runway }: { pace: Pace | undefined; runway: Runway | undefined }) {
  const [mode, setMode] = useState<SignalMode>(() => readSignalMode(storage()));
  const v = signalValue(mode, pace, runway) ?? signalValue(mode === "ratio" ? "safe" : "ratio", pace, runway);
  if (!v) return null;
  const flip = () => {
    const next: SignalMode = mode === "ratio" ? "safe" : "ratio";
    setMode(next);
    storage()?.setItem(SIGNAL_KEY, next);
  };
  return (
    <button
      type="button"
      onClick={flip}
      aria-label={`${v.label}. הקשה מחליפה מדד`}
      className="flex flex-col items-start text-start text-[var(--hero-text)] transition-opacity duration-200 active:opacity-70"
    >
      <span className="text-[13px] text-[var(--hero-muted)]">{v.label}</span>
      <span className="flex items-baseline gap-1.5 font-display text-xl font-semibold tabular-nums">
        <Money>{v.unit === "%" ? pct(v.value) : shekel(v.value)}</Money>
        <span aria-hidden className="text-xs text-[var(--hero-muted)]">{v.good ? "▲" : "▼"}</span>
      </span>
    </button>
  );
}
