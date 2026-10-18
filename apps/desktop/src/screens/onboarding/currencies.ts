/**
 * The currencies offered when setting up, and the default guessed from the user's locale.
 *
 * Only currencies with two decimal places are listed: amounts are stored as integer cents,
 * which does not fit zero-decimal currencies such as JPY or KRW.
 */

export const FALLBACK_CURRENCY = "USD";

/** ISO 4217 codes, each with a region whose locale defaults to it. */
const CURRENCY_REGIONS = {
  AED: ["AE"],
  AUD: ["AU"],
  BRL: ["BR"],
  CAD: ["CA"],
  CHF: ["CH", "LI"],
  CNY: ["CN"],
  CZK: ["CZ"],
  DKK: ["DK", "GL", "FO"],
  EUR: [
    "AT",
    "BE",
    "CY",
    "DE",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PT",
    "SI",
    "SK",
  ],
  GBP: ["GB"],
  HKD: ["HK"],
  ILS: ["IL"],
  INR: ["IN"],
  MXN: ["MX"],
  NOK: ["NO"],
  NZD: ["NZ"],
  PHP: ["PH"],
  PKR: ["PK"],
  PLN: ["PL"],
  SAR: ["SA"],
  SEK: ["SE"],
  SGD: ["SG"],
  USD: ["US", "PR"],
  ZAR: ["ZA"],
} as const satisfies Record<string, readonly string[]>;

export type CurrencyCode = keyof typeof CURRENCY_REGIONS;

export const CURRENCY_CODES = Object.keys(CURRENCY_REGIONS) as CurrencyCode[];

const CURRENCY_BY_REGION = new Map<string, CurrencyCode>(
  CURRENCY_CODES.flatMap((code) =>
    CURRENCY_REGIONS[code].map((region): [string, CurrencyCode] => [region, code]),
  ),
);

/** The currency of the locale's region, e.g. `en-CA` → `CAD`, or `undefined` if not listed. */
export function currencyForLocale(
  locale: string,
  { guessRegion = true }: { guessRegion?: boolean } = {},
): CurrencyCode | undefined {
  let parsed: Intl.Locale;
  try {
    parsed = new Intl.Locale(locale);
  } catch {
    return undefined; // Not a valid language tag.
  }
  // A bare language like "fr" has no region; maximize() adds its most likely one ("FR").
  const region = parsed.region ?? (guessRegion ? parsed.maximize().region : undefined);
  return region === undefined ? undefined : CURRENCY_BY_REGION.get(region);
}

/**
 * The currency to preselect for someone whose preferred languages are `locales` (most
 * preferred first, like `navigator.languages`).
 *
 * A locale that names its region wins over a guessed one, so `["en", "en-CA"]` gives CAD
 * rather than the USD that a bare "en" suggests.
 */
export function defaultCurrency(locales: readonly string[]): CurrencyCode {
  for (const guessRegion of [false, true]) {
    for (const locale of locales) {
      const currency = currencyForLocale(locale, { guessRegion });
      if (currency !== undefined) return currency;
    }
  }
  return FALLBACK_CURRENCY;
}

/** `"CAD"` → `"Canadian Dollar (CAD)"`, with the name in the user's language. */
export function currencyLabel(code: string, locale?: string): string {
  const name = new Intl.DisplayNames(locale, { type: "currency" }).of(code);
  return name === undefined || name === code ? code : `${name} (${code})`;
}

/** Every offered currency with its label, sorted by name the way the user reads it. */
export function currencyOptions(locale?: string): { code: CurrencyCode; label: string }[] {
  const collator = new Intl.Collator(locale);
  return CURRENCY_CODES.map((code) => ({ code, label: currencyLabel(code, locale) })).sort((a, b) =>
    collator.compare(a.label, b.label),
  );
}
