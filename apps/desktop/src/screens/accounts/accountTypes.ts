import { CreditCard, Landmark, PiggyBank, Wallet, type LucideIcon } from "lucide-react";

import type { Schemas } from "@/api/client";

export type AccountType = Schemas["AccountType"];

interface AccountTypeInfo {
  value: AccountType;
  label: string;
  icon: LucideIcon;
}

/** Every account type, in the order the add form lists them. */
export const ACCOUNT_TYPES: readonly AccountTypeInfo[] = [
  { value: "checking", label: "Checking", icon: Landmark },
  { value: "savings", label: "Savings", icon: PiggyBank },
  { value: "credit_card", label: "Credit card", icon: CreditCard },
  { value: "other", label: "Other", icon: Wallet },
];

export function accountTypeInfo(type: AccountType): AccountTypeInfo {
  const info = ACCOUNT_TYPES.find((candidate) => candidate.value === type);
  if (!info) throw new RangeError(`Unknown account type: ${type}`);
  return info;
}

/** Currencies offered when adding an account (ISO 4217). */
export const CURRENCIES: readonly string[] = [
  "CAD",
  "USD",
  "EUR",
  "GBP",
  "AUD",
  "NZD",
  "CHF",
  "INR",
  "MXN",
];

/** The engine's limit for account names and institutions. */
export const MAX_NAME_LENGTH = 100;
