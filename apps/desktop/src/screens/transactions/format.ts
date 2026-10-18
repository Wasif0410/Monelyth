const countFormat = new Intl.NumberFormat();

/** `1284` → `"1,284 transactions"` (in an English locale). */
export function transactionCount(count: number): string {
  return `${countFormat.format(count)} ${count === 1 ? "transaction" : "transactions"}`;
}
