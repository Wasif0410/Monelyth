/** Engine response fixtures shared by screen tests. Spread overrides over the defaults. */
import type { Account } from "@/api/queries";
import type { CategorizationStatus } from "@/screens/review/queries";
import type { Rule } from "@/screens/rules/queries";

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

export function makeRule(overrides: Partial<Rule> & Pick<Rule, "id" | "pattern">): Rule {
  return {
    match_type: "contains",
    category_id: 1,
    priority: 0,
    created_by: "user",
    ...overrides,
  };
}

/** Background categorization with nothing going on. */
export function makeCategorizationStatus(
  overrides: Partial<CategorizationStatus> = {},
): CategorizationStatus {
  return {
    state: "idle",
    processed: 0,
    total: 0,
    last_error: null,
    runs_finished: 1,
    ...overrides,
  };
}
