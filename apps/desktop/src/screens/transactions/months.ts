/** Calendar-month arithmetic on `YYYY-MM` strings, which also sort chronologically as text. */
import type { Month } from "@/screens/transactions/filters";

/** `"2026-09-14"` → `"2026-09"`. */
export function monthOf(isoDate: string): Month {
  return isoDate.slice(0, 7);
}

/** `shiftMonth("2026-01", -1)` → `"2025-12"`. */
export function shiftMonth(month: Month, delta: number): Month {
  const [year, monthNumber] = parts(month);
  const index = year * 12 + (monthNumber - 1) + delta;
  return toMonth(Math.floor(index / 12), (index % 12) + 1);
}

/** Every month from `last` back to `first`, newest first; empty if `first` is after `last`. */
export function monthsBetween(first: Month, last: Month): Month[] {
  const months: Month[] = [];
  for (let month = last; month >= first; month = shiftMonth(month, -1)) months.push(month);
  return months;
}

/** `"2026-09"` → `"September 2026"` (in an English locale). */
export function formatMonth(month: Month, locale?: string): string {
  const [year, monthNumber] = parts(month);
  return new Date(year, monthNumber - 1, 1).toLocaleDateString(locale, {
    month: "long",
    year: "numeric",
  });
}

function parts(month: Month): [number, number] {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) throw new RangeError(`Invalid month: ${month}`);
  return [Number(match[1]), Number(match[2])];
}

function toMonth(year: number, monthNumber: number): Month {
  return `${String(year).padStart(4, "0")}-${String(monthNumber).padStart(2, "0")}`;
}
