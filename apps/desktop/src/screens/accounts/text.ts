import type { Account } from "@/api/queries";

/** `1, "transaction"` → `1 transaction`; `1580, "transaction"` → `1,580 transactions`. */
export function countOf(count: number, singular: string, plural = `${singular}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

/** Exactly what goes, e.g. "Deletes Main Checking and its 158 transactions. This can't be undone." */
export function deletionSummary(account: Account): string {
  const what =
    account.transaction_count === 0
      ? `${account.name}, which has no transactions`
      : `${account.name} and its ${countOf(account.transaction_count, "transaction")}`;
  return `Deletes ${what}. This can't be undone.`;
}
