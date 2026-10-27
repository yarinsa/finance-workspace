import type { Horizon } from "@/lib/api";
import type { GoalCreateInput } from "@/__generated__/GoalEditorSheetCreateMutation.graphql";
import type { GoalInterval, GoalUpdateInput, HorizonKey } from "@/__generated__/GoalEditorSheetUpdateMutation.graphql";

/** The editor's fields as typed by the user (all text, so partial input is representable). */
export interface GoalFormValues {
  description: string;
  amount: string;
  startDate: string;
  endDate: string;
  interval: GoalInterval | "";
  repetitions: string;
  rise: string;
  horizon: Horizon | null;
}

export type GoalFormErrors = Partial<Record<"description" | "amount" | "startDate" | "endDate" | "repetitions" | "rise", string>>;

export const EMPTY_GOAL_FORM: GoalFormValues = {
  description: "",
  amount: "",
  startDate: "",
  endDate: "",
  interval: "",
  repetitions: "1",
  rise: "0",
  horizon: null,
};

/** True for a real calendar day written as YYYY-MM-DD (rejects 2027-02-30 and free text). */
export function isIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

/** Parse a decimal typed in a number input; null when empty or not a finite number. */
function num(s: string): number | null {
  if (!s.trim()) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Errors per field (Hebrew); an empty object means the form can be saved. */
export function validateGoalForm(f: GoalFormValues): GoalFormErrors {
  const errors: GoalFormErrors = {};
  if (!f.description.trim()) errors.description = "תיאור נדרש";
  const amount = num(f.amount);
  if (!f.amount.trim()) errors.amount = "סכום נדרש";
  else if (amount == null || amount <= 0) errors.amount = "סכום חייב להיות חיובי";
  if (f.startDate && !isIsoDate(f.startDate)) errors.startDate = "תאריך התחלה לא תקין";
  if (f.endDate && !isIsoDate(f.endDate)) errors.endDate = "תאריך סיום לא תקין";
  if (f.startDate && f.endDate && !errors.startDate && !errors.endDate && f.endDate < f.startDate) {
    errors.endDate = "תאריך הסיום לפני ההתחלה";
  }
  if (f.interval && f.repetitions.trim()) {
    const reps = num(f.repetitions);
    if (reps == null || !Number.isInteger(reps) || reps < 1) errors.repetitions = "מספר חזרות שלם, לפחות 1";
  }
  if (f.rise.trim()) {
    const rise = num(f.rise);
    if (rise == null || rise < 0) errors.rise = "עלייה לא יכולה להיות שלילית";
  }
  return errors;
}

const money = (n: number) => n.toFixed(2);
const horizonKey = (h: Horizon | null): HorizonKey | null => (h ? (h.toUpperCase() as HorizonKey) : null);
const repsOf = (f: GoalFormValues): number => (f.interval ? (num(f.repetitions) ?? 1) : 1);
const riseOf = (f: GoalFormValues): number => num(f.rise) ?? 0;

/** The create input: only the fields that carry a value are sent. Assumes `validateGoalForm` passed. */
export function buildCreateInput(f: GoalFormValues): GoalCreateInput {
  const reps = repsOf(f);
  const rise = riseOf(f);
  return {
    description: f.description.trim(),
    amount: money(Number(f.amount)),
    ...(f.startDate ? { startDate: f.startDate } : {}),
    ...(f.endDate ? { endDate: f.endDate } : {}),
    ...(f.interval ? { interval: f.interval } : {}),
    ...(f.interval && reps > 1 ? { repetitions: reps } : {}),
    ...(rise > 0 ? { rise: money(rise) } : {}),
    ...(f.horizon ? { horizon: horizonKey(f.horizon) } : {}),
  };
}

/**
 * The update input: only fields that differ from `initial` are present; a field the user
 * cleared (end date, start date, interval, horizon, rise) is `null`, which clears it on the
 * server. Description and amount can only change, never clear (validation guarantees it).
 */
export function buildUpdateInput(f: GoalFormValues, initial: GoalFormValues): GoalUpdateInput {
  const out: GoalUpdateInput = {};
  if (f.description.trim() !== initial.description.trim()) out.description = f.description.trim();
  if (Number(f.amount) !== Number(initial.amount)) out.amount = money(Number(f.amount));
  if (f.startDate !== initial.startDate) out.startDate = f.startDate || null;
  if (f.endDate !== initial.endDate) out.endDate = f.endDate || null;
  if (f.interval !== initial.interval) out.interval = f.interval || null;
  if (repsOf(f) !== repsOf(initial)) out.repetitions = repsOf(f);
  if (riseOf(f) !== riseOf(initial)) out.rise = riseOf(f) > 0 ? money(riseOf(f)) : null;
  if (f.horizon !== initial.horizon) out.horizon = horizonKey(f.horizon);
  return out;
}
