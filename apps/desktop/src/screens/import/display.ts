/** Wording and number formatting for the import screen. */
import { formatMoney } from "@/lib/format";

const plainAmount = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Format integer cents in `currency`. Before the user has picked an account, a CSV statement's
 * currency is unknown, so the amount is shown as a plain number rather than in a guessed one.
 */
export function formatAmount(cents: number, currency: string | null): string {
  if (currency !== null) return formatMoney(cents, currency);
  const absolute = Math.abs(cents);
  const whole = String(Math.trunc(absolute / 100));
  const fraction = String(absolute % 100).padStart(2, "0");
  // A decimal string keeps every cent exact, as in formatMoney.
  return plainAmount.format(
    `${cents < 0 ? "-" : ""}${whole}.${fraction}` as Intl.StringNumericLiteral,
  );
}

/** `2026-10-03T14:05:00+00:00` → `Oct 3, 2026`, in the user's time zone. */
export function formatTimestampDate(iso: string, locale?: string): string {
  return new Date(iso).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** `1 transaction`, `84 transactions`. */
export function plural(count: number, singular: string): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : `${singular}s`}`;
}

/** `a`, `a and b`, `a, b and c`. */
export function joinAnd(items: readonly string[]): string {
  const last = items.at(-1);
  if (last === undefined) return "";
  return items.length === 1 ? last : `${items.slice(0, -1).join(", ")} and ${last}`;
}

/** The headline after an import, e.g. "Added 84 transactions, skipped 12 duplicates". */
export function importHeadline(added: number, skippedDuplicates: number): string {
  const skipped = `skipped ${plural(skippedDuplicates, "duplicate")}`;
  if (added === 0) return `No new transactions: ${skipped}`;
  const addedText = `Added ${plural(added, "transaction")}`;
  return skippedDuplicates === 0 ? addedText : `${addedText}, ${skipped}`;
}
