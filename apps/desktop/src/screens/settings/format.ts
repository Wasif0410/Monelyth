const UNITS = ["kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

/**
 * A file size for people, e.g. `1_572_864` → `1.5 MB` (in an English locale). Never smaller
 * than kilobytes: a database is always at least a few of them.
 */
export function formatBytes(bytes: number, locale?: string): string {
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: UNITS[unit] ?? "kilobyte",
    unitDisplay: "short",
    maximumFractionDigits: value < 10 ? 1 : 0,
  }).format(value);
}
