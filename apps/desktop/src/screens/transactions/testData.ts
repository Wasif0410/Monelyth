/** Fixtures and jsdom set-up shared by the Transactions screen tests. */
import { vi } from "vitest";

import type { Account, Category } from "@/api/queries";
import type { Transaction } from "@/screens/transactions/hooks";

export const accounts: Account[] = [
  { id: 1, name: "Everyday Chequing", institution: "TD", type: "checking", currency: "CAD" },
  { id: 2, name: "Travel Visa", institution: null, type: "credit_card", currency: "USD" },
];

export const categories: Category[] = [
  { id: 1, name: "Salary", kind: "income", parent_id: null },
  { id: 5, name: "Groceries", kind: "expense", parent_id: null },
  { id: 6, name: "Dining Out", kind: "expense", parent_id: null },
  { id: 19, name: "Transfers", kind: "transfer", parent_id: null },
];

export function transaction(
  overrides: Partial<Transaction> & Pick<Transaction, "id">,
): Transaction {
  return {
    account_id: 1,
    import_id: 1,
    posted_date: "2026-10-02",
    amount_cents: -1000,
    description_raw: `PURCHASE ${String(overrides.id)}`,
    merchant: null,
    category_id: null,
    category_source: null,
    confidence: null,
    needs_review: false,
    transfer_group: null,
    ...overrides,
  };
}

export const groceries = transaction({
  id: 3,
  posted_date: "2026-10-02",
  amount_cents: -8210,
  description_raw: "POS PURCHASE LOBLAWS #1031 TORONTO ON",
  merchant: "Loblaws",
});
export const payroll = transaction({
  id: 2,
  posted_date: "2026-09-30",
  amount_cents: 250000,
  description_raw: "PAYROLL ACME CORP",
  merchant: "Acme Corp",
  category_id: 1,
  category_source: "user",
});
export const bookstore = transaction({
  id: 1,
  account_id: 2,
  posted_date: "2026-09-14",
  amount_cents: -1299,
  description_raw: "AMZN MKTP US*2K3 BOOKS",
  needs_review: true,
});

export const range = { first_date: "2026-08-03", last_date: "2026-10-02" };

/** The height jsdom reports for every element, so the virtualized table has a viewport. */
export const VIEWPORT_HEIGHT = 600;

/**
 * jsdom does no layout: give elements a size (the virtualizer renders nothing in a 0px
 * viewport) and add the browser APIs Radix calls. Call in `beforeEach`; the spies and stubs
 * are restored after each test.
 */
export function stubLayout() {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(VIEWPORT_HEIGHT);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1000);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    },
  );
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  Element.prototype.releasePointerCapture = vi.fn();
}
