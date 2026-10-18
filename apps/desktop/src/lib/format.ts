/** Display formatting for money and dates. Always format through these so the app is consistent. */

const moneyFormatters = new Map<string, Intl.NumberFormat>();

/**
 * Format integer cents as currency, e.g. `-1299, "CAD"` → `-$12.99` (in an English locale).
 * Uses exact integer arithmetic, so no floating-point rounding can creep in.
 */
export function formatMoney(cents: number, currency: string, locale?: string): string {
  if (!Number.isSafeInteger(cents)) throw new RangeError(`Invalid cents: ${String(cents)}`);
  const key = `${locale ?? ""}|${currency}`;
  let formatter = moneyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      // Amounts are stored in cents, so always show them. Some currencies (e.g. PKR) default
      // to no decimals, which would silently round what the user sees.
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    moneyFormatters.set(key, formatter);
  }
  // Intl accepts a decimal string, which keeps every cent exact.
  const negative = cents < 0;
  const absolute = Math.abs(cents);
  const whole = Math.trunc(absolute / 100);
  const fraction = String(absolute % 100).padStart(2, "0");
  // Always of the form "-123.45", which is a valid numeric string.
  const decimal = `${negative ? "-" : ""}${String(whole)}.${fraction}` as Intl.StringNumericLiteral;
  return formatter.format(decimal);
}

/** Parse an ISO `YYYY-MM-DD` date as a calendar date (no timezone shift). */
export function parseIsoDate(iso: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) throw new RangeError(`Invalid ISO date: ${iso}`);
  const [, year, month, day] = match;
  return new Date(Number(year), Number(month) - 1, Number(day));
}

/** `2026-09-14` → `Sep 14, 2026` (in an English locale). */
export function formatDate(iso: string, locale?: string): string {
  return parseIsoDate(iso).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
