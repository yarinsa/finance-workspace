// The home "בקרוב" week strip: the next seven days from the runway's events.
import type { Runway } from "./data";

export type RunwayEvent = Runway["events"][number];

export interface WeekDay {
  date: string;
  /** א׳ … ש׳ */
  dow: string;
  day: number;
  today: boolean;
  events: RunwayEvent[];
}

const DOW = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"];

export function weekDays(runway: Pick<Runway, "as_of" | "events">, n = 7): WeekDay[] {
  const start = new Date(`${runway.as_of}T00:00:00Z`);
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(start);
    d.setUTCDate(start.getUTCDate() + i);
    const iso = d.toISOString().slice(0, 10);
    return {
      date: iso,
      dow: DOW[d.getUTCDay()],
      day: d.getUTCDate(),
      today: i === 0,
      events: runway.events.filter((e) => e.date === iso),
    };
  });
}

/** The day the strip opens on: the first one with money moving, else today. */
export function initialDay(days: WeekDay[]): string {
  return (days.find((d) => d.events.length) ?? days[0])?.date ?? "";
}

/** After the strip: the next event beyond it, so a quiet week still says what comes next. */
export function nextBeyond(runway: Pick<Runway, "events">, days: WeekDay[]): RunwayEvent | null {
  const last = days.at(-1)?.date ?? "";
  return runway.events.find((e) => e.date > last) ?? null;
}
