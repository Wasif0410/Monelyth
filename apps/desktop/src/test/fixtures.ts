/** Engine response fixtures shared by screen tests. Spread overrides over the defaults. */
import type { Account } from "@/api/queries";

export function makeAccount(overrides: Partial<Account> & Pick<Account, "id" | "name">): Account {
  return {
    institution: null,
    type: "checking",
    currency: "CAD",
    transaction_count: 0,
    latest_transaction_date: null,
    net_amount_cents: 0,
    ...overrides,
  };
}
