import { describe, expect, it } from "vitest";

import { formatDate, formatMoney, parseIsoDate } from "@/lib/format";

describe("formatMoney", () => {
  it.each([
    [0, "$0.00"],
    [5, "$0.05"],
    [-1299, "-$12.99"],
    [123456789, "$1,234,567.89"],
    [-100, "-$1.00"],
  ])("formats %i cents", (cents, expected) => {
    expect(formatMoney(cents, "USD", "en-US")).toBe(expected);
  });

  it("is exact for amounts where floats would round", () => {
    // 0.1 + 0.2 style errors would show up here if cents were divided as floats.
    expect(formatMoney(900719925474099, "USD", "en-US")).toBe("$9,007,199,254,740.99");
  });

  it("uses the currency given", () => {
    expect(formatMoney(1050, "EUR", "en-US")).toBe("€10.50");
  });

  it("rejects non-integer cents", () => {
    expect(() => formatMoney(10.5, "USD")).toThrow(RangeError);
  });
});

describe("dates", () => {
  it("parses ISO dates as calendar dates without a timezone shift", () => {
    const date = parseIsoDate("2026-01-01");

    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([2026, 0, 1]);
  });

  it("formats a readable date", () => {
    expect(formatDate("2026-09-14", "en-US")).toBe("Sep 14, 2026");
  });

  it.each(["2026-9-14", "14/09/2026", ""])("rejects %j", (value) => {
    expect(() => parseIsoDate(value)).toThrow(RangeError);
  });
});
