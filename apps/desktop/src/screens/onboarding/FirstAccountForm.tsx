import { ArrowLeft, LoaderCircle } from "lucide-react";
import { useId, useState, type SubmitEvent } from "react";

import { useCreateAccount, type Account, type AccountCreate } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CurrencyCode } from "@/screens/onboarding/currencies";
import { CurrencySelect } from "@/screens/onboarding/CurrencySelect";
import { InlineError } from "@/screens/onboarding/InlineError";

type AccountType = AccountCreate["type"];

const ACCOUNT_TYPES: readonly { value: AccountType; label: string }[] = [
  { value: "checking", label: "Checking" },
  { value: "savings", label: "Savings" },
  { value: "credit_card", label: "Credit card" },
  { value: "other", label: "Other" },
];

/** Matches the engine's limit, so a long name is stopped while typing rather than refused. */
const MAX_NAME_LENGTH = 100;

interface FirstAccountFormProps {
  currency: CurrencyCode;
  onBack: () => void;
  onCreated: (account: Account) => void;
}

/** The account a first statement is imported into: just a name, a type and a currency. */
export function FirstAccountForm({
  currency: initialCurrency,
  onBack,
  onCreated,
}: FirstAccountFormProps) {
  const createAccount = useCreateAccount();
  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("checking");
  const [currency, setCurrency] = useState(initialCurrency);
  const [nameMissing, setNameMissing] = useState(false);
  const ids = {
    heading: useId(),
    name: useId(),
    nameError: useId(),
    type: useId(),
    currency: useId(),
  };

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setNameMissing(true);
      return;
    }
    createAccount.mutate({ name: trimmed, type, currency }, { onSuccess: onCreated });
  }

  const busy = createAccount.isPending;
  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby={ids.heading}
      className="flex flex-col gap-5"
    >
      <div>
        <h2 id={ids.heading} className="text-lg font-semibold tracking-tight">
          Add your first account
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          The account your statement belongs to. You can add more later.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.name}>Account name</Label>
        <Input
          id={ids.name}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            if (event.target.value.trim()) setNameMissing(false);
          }}
          placeholder="e.g. Everyday Checking"
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
          autoFocus
          disabled={busy}
          aria-invalid={nameMissing || undefined}
          aria-describedby={nameMissing ? ids.nameError : undefined}
        />
        {nameMissing ? (
          <p id={ids.nameError} className="text-destructive text-sm">
            Give the account a name, like the one your bank uses.
          </p>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.type}>Type</Label>
          <Select
            value={type}
            onValueChange={(next) => {
              const option = ACCOUNT_TYPES.find((candidate) => candidate.value === next);
              if (option) setType(option.value);
            }}
            disabled={busy}
          >
            <SelectTrigger id={ids.type} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACCOUNT_TYPES.map(({ value, label }) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.currency}>Currency</Label>
          <CurrencySelect
            id={ids.currency}
            value={currency}
            onChange={setCurrency}
            disabled={busy}
          />
        </div>
      </div>

      {createAccount.isError ? <InlineError error={createAccount.error} /> : null}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button type="button" variant="ghost" onClick={onBack} disabled={busy}>
          <ArrowLeft aria-hidden="true" />
          Back
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? (
            <LoaderCircle aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : null}
          {busy ? "Adding account…" : "Add account and import"}
        </Button>
      </div>
    </form>
  );
}
