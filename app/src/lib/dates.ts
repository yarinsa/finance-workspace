/**
 * Safe date formatting: returns null for missing/invalid dates instead of throwing.
 */
export function fmt(formatter: Intl.DateTimeFormat, iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return formatter.format(new Date(iso));
  } catch {
    return null;
  }
}

/**
 * Safe date parsing: returns 0 for missing/invalid dates (safe for Math.max/min).
 */
export function toTime(iso: string | null | undefined): number {
  if (!iso) return 0;
  try {
    const time = new Date(iso).getTime();
    return isNaN(time) ? 0 : time;
  } catch {
    return 0;
  }
}
