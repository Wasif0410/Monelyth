import { describe, expect, it } from "vitest";

import {
  filtersToSearchParams,
  hasActiveFilters,
  NO_FILTERS,
  parseFilters,
  toListQuery,
  transactionsLink,
  type TransactionFilters,
} from "@/screens/transactions/filters";
import { formatMonth, monthOf, monthsBetween, shiftMonth } from "@/screens/transactions/months";

const everything: TransactionFilters = {
  search: "coffee shop",
  accountId: 2,
  month: "2026-09",
  category: 7,
  needsReview: true,
};

describe("transactionsLink", () => {
  it("links to the unfiltered list by default", () => {
    expect(transactionsLink()).toBe("/transactions");
    expect(transactionsLink({ category: null, search: "  " })).toBe("/transactions");
  });

  it("links to exactly the given filters", () => {
    expect(transactionsLink({ category: 7, month: "2026-09" })).toBe(
      "/transactions?month=2026-09&category=7",
    );
    expect(transactionsLink({ category: "uncategorized", needsReview: true })).toBe(
      "/transactions?category=uncategorized&review=1",
    );
    expect(transactionsLink(everything)).toBe(
      "/transactions?q=coffee+shop&account=2&month=2026-09&category=7&review=1",
    );
  });
});

describe("parseFilters", () => {
  it("reads back what filtersToSearchParams writes", () => {
    expect(parseFilters(filtersToSearchParams(everything))).toEqual(everything);
    expect(parseFilters(filtersToSearchParams(NO_FILTERS))).toEqual(NO_FILTERS);
    expect(parseFilters(new URLSearchParams("category=uncategorized")).category).toBe(
      "uncategorized",
    );
  });

  it.each([
    "account=0",
    "account=-1",
    "account=1.5",
    "account=abc",
    "account=99999999999999999999",
    "month=2026-13",
    "month=2026-9",
    "month=september",
    "category=none",
    "category=",
    "review=true",
  ])("ignores the invalid value in %s", (query) => {
    expect(parseFilters(new URLSearchParams(query))).toEqual(NO_FILTERS);
  });

  it("caps the search at what the engine accepts", () => {
    expect(parseFilters(new URLSearchParams({ q: "a".repeat(300) })).search).toHaveLength(200);
  });
});

describe("hasActiveFilters", () => {
  it("is false only when nothing narrows the list", () => {
    expect(hasActiveFilters(NO_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...NO_FILTERS, search: "   " })).toBe(false);
    expect(hasActiveFilters({ ...NO_FILTERS, needsReview: true })).toBe(true);
  });
});

describe("toListQuery", () => {
  it("leaves out filters that aren't applied", () => {
    expect(toListQuery(NO_FILTERS)).toEqual({});
  });

  it("turns each filter into the engine's parameters", () => {
    expect(toListQuery(everything)).toEqual({
      q: "coffee shop",
      account_id: 2,
      date_from: "2026-09-01",
      date_to: "2026-09-30",
      category_id: 7,
      needs_review: true,
    });
    expect(toListQuery({ ...NO_FILTERS, category: "uncategorized" })).toEqual({
      categorized: false,
    });
  });

  it.each([
    ["2026-02", "2026-02-28"],
    ["2028-02", "2028-02-29"],
    ["2026-12", "2026-12-31"],
    ["2026-04", "2026-04-30"],
  ])("ends %s on its last day", (month, last) => {
    expect(toListQuery({ ...NO_FILTERS, month })).toEqual({
      date_from: `${month}-01`,
      date_to: last,
    });
  });
});

describe("months", () => {
  it("steps across year boundaries", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2025-12", 1)).toBe("2026-01");
    expect(shiftMonth("2026-05", -17)).toBe("2024-12");
  });

  it("lists months newest first", () => {
    expect(monthsBetween("2025-11", "2026-02")).toEqual([
      "2026-02",
      "2026-01",
      "2025-12",
      "2025-11",
    ]);
    expect(monthsBetween("2026-02", "2026-02")).toEqual(["2026-02"]);
    expect(monthsBetween("2026-03", "2026-02")).toEqual([]);
  });

  it("reads the month of a date and names it", () => {
    expect(monthOf("2026-09-14")).toBe("2026-09");
    expect(formatMonth("2026-09", "en-US")).toBe("September 2026");
  });
});
