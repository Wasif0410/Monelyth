/**
 * The Transactions screen's filters and how they live in the URL, so any screen can link to an
 * exact filtered view ("every number is clickable"). Use `transactionsLink` to build such links.
 *
 * URL format (every parameter is optional; an invalid value is ignored):
 *
 * | Parameter  | Value                              | Example                  |
 * |------------|------------------------------------|--------------------------|
 * | `q`        | search text                        | `q=coffee`               |
 * | `account`  | account id                         | `account=2`              |
 * | `month`    | calendar month, `YYYY-MM`          | `month=2026-09`          |
 * | `category` | category id, or `uncategorized`    | `category=uncategorized` |
 * | `review`   | `1` to show only "needs review"    | `review=1`               |
 */
import type { paths as ApiPaths } from "@/api/schema";
import { paths } from "@/paths";

/** A calendar month as `YYYY-MM`, e.g. `"2026-09"`. */
export type Month = string;

export const UNCATEGORIZED = "uncategorized";

export interface TransactionFilters {
  /** Search text matched against the bank description and the merchant; `""` for none. */
  search: string;
  accountId: number | null;
  /** `null` for all time. */
  month: Month | null;
  /** A category id, `"uncategorized"` for transactions without one, or `null` for any. */
  category: number | typeof UNCATEGORIZED | null;
  /** Only transactions waiting in the review queue. */
  needsReview: boolean;
}

export const NO_FILTERS: TransactionFilters = {
  search: "",
  accountId: null,
  month: null,
  category: null,
  needsReview: false,
};

/** The longest search text the engine accepts. */
export const MAX_SEARCH_LENGTH = 200;

const PARAM = {
  search: "q",
  account: "account",
  month: "month",
  category: "category",
  review: "review",
} as const;

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

/**
 * A link to the Transactions screen showing exactly these filters, e.g.
 * `transactionsLink({ category: 7, month: "2026-09" })` → `/transactions?month=2026-09&category=7`.
 * Filters left out are not applied.
 */
export function transactionsLink(filters: Partial<TransactionFilters> = {}): string {
  const query = filtersToSearchParams({ ...NO_FILTERS, ...filters }).toString();
  return query ? `${paths.transactions}?${query}` : paths.transactions;
}

/** Read the filters from the URL, ignoring any value that isn't valid. */
export function parseFilters(params: URLSearchParams): TransactionFilters {
  const month = params.get(PARAM.month);
  const category = params.get(PARAM.category);
  return {
    search: (params.get(PARAM.search) ?? "").slice(0, MAX_SEARCH_LENGTH),
    accountId: parseId(params.get(PARAM.account)),
    month: month !== null && MONTH_PATTERN.test(month) ? month : null,
    category: category === UNCATEGORIZED ? UNCATEGORIZED : parseId(category),
    needsReview: params.get(PARAM.review) === "1",
  };
}

/** The URL parameters for these filters; filters that aren't applied are left out. */
export function filtersToSearchParams(filters: TransactionFilters): URLSearchParams {
  const params = new URLSearchParams();
  const search = filters.search.trim();
  if (search) params.set(PARAM.search, search);
  if (filters.accountId !== null) params.set(PARAM.account, String(filters.accountId));
  if (filters.month !== null) params.set(PARAM.month, filters.month);
  if (filters.category !== null) params.set(PARAM.category, String(filters.category));
  if (filters.needsReview) params.set(PARAM.review, "1");
  return params;
}

export function hasActiveFilters(filters: TransactionFilters): boolean {
  return filtersToSearchParams(filters).size > 0;
}

type ListParameters = NonNullable<ApiPaths["/transactions"]["get"]["parameters"]["query"]>;

/** The `GET /transactions` filter parameters, without paging. Unused filters are left out. */
export type ListQuery = Omit<ListParameters, "limit" | "offset">;

export function toListQuery(filters: TransactionFilters): ListQuery {
  const query: ListQuery = {};
  const search = filters.search.trim();
  if (search) query.q = search;
  if (filters.accountId !== null) query.account_id = filters.accountId;
  if (filters.month !== null) {
    query.date_from = `${filters.month}-01`;
    query.date_to = lastDayOfMonth(filters.month);
  }
  if (filters.category === UNCATEGORIZED) query.categorized = false;
  else if (filters.category !== null) query.category_id = filters.category;
  if (filters.needsReview) query.needs_review = true;
  return query;
}

/** `"2026-09"` → `"2026-09-30"`. */
function lastDayOfMonth(month: Month): string {
  const [year, monthNumber] = month.split("-").map(Number) as [number, number];
  // Day 0 of the next month is the last day of this one.
  const days = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  return `${month}-${String(days).padStart(2, "0")}`;
}

function parseId(value: string | null): number | null {
  if (value === null || !/^[1-9]\d{0,15}$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
