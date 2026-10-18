import { describe, expect, it } from "vitest";

import {
  CURRENCY_CODES,
  currencyForLocale,
  currencyLabel,
  currencyOptions,
  defaultCurrency,
  FALLBACK_CURRENCY,
} from "@/screens/onboarding/currencies";

describe("currencyForLocale", () => {
  it.each([
    ["en-CA", "CAD"],
    ["fr-CA", "CAD"],
    ["en-US", "USD"],
    ["en-GB", "GBP"],
    ["de-DE", "EUR"],
    ["de-AT", "EUR"],
    ["de-CH", "CHF"],
    ["en-IN", "INR"],
    ["ur-PK", "PKR"],
    ["en-AU", "AUD"],
  ])("maps %s to %s", (locale, currency) => {
    expect(currencyForLocale(locale)).toBe(currency);
  });

  it("guesses the region of a bare language", () => {
    expect(currencyForLocale("fr")).toBe("EUR");
    expect(currencyForLocale("en")).toBe("USD");
    expect(currencyForLocale("fr", { guessRegion: false })).toBeUndefined();
  });

  it("returns nothing for an unlisted currency or an invalid tag", () => {
    expect(currencyForLocale("ja-JP")).toBeUndefined();
    expect(currencyForLocale("not a locale!")).toBeUndefined();
    expect(currencyForLocale("")).toBeUndefined();
  });
});

describe("defaultCurrency", () => {
  it("uses the first locale that names a listed region", () => {
    expect(defaultCurrency(["en-CA"])).toBe("CAD");
    expect(defaultCurrency(["ja-JP", "en-GB"])).toBe("GBP");
  });

  it("prefers an explicit region over one guessed from a bare language", () => {
    expect(defaultCurrency(["en", "en-CA"])).toBe("CAD");
    expect(defaultCurrency(["fr"])).toBe("EUR");
  });

  it("falls back to USD", () => {
    expect(FALLBACK_CURRENCY).toBe("USD");
    expect(defaultCurrency([])).toBe("USD");
    expect(defaultCurrency(["ja-JP", "???"])).toBe("USD");
  });
});

describe("currency list", () => {
  it("only offers currencies with two decimal places, since amounts are stored in cents", () => {
    // ISO 4217 currencies whose minor unit is not 1/100.
    const notCents = new Set(
      "BHD BIF CLP DJF GNF IQD ISK JOD JPY KMF KRW KWD LYD OMR PYG RWF TND UGX VND VUV".split(" "),
    );

    expect(CURRENCY_CODES.filter((code) => notCents.has(code))).toEqual([]);
  });

  it("labels each currency by name and code", () => {
    expect(currencyLabel("CAD", "en")).toBe("Canadian Dollar (CAD)");
    expect(currencyLabel("EUR", "fr")).toBe("euro (EUR)");
  });

  it("lists every currency once, sorted by name", () => {
    const options = currencyOptions("en");
    const labels = options.map((option) => option.label);

    expect(options.map((option) => option.code).sort()).toEqual([...CURRENCY_CODES].sort());
    expect(labels).toEqual([...labels].sort((a, b) => a.localeCompare(b, "en")));
  });
});
