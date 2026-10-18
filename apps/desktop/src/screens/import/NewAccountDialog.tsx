import { LoaderCircle } from "lucide-react";
import { useId, useState, type SubmitEvent } from "react";

import { useCreateAccount, type Account, type AccountCreate } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { errorMessage } from "@/lib/utils";
import { Notice } from "@/screens/import/Notice";

type AccountType = AccountCreate["type"];

const ACCOUNT_TYPES: readonly { value: AccountType; label: string }[] = [
  { value: "checking", label: "Checking" },
  { value: "savings", label: "Savings" },
  { value: "credit_card", label: "Credit card" },
  { value: "other", label: "Other" },
];

const CURRENCY_CODE = /^[A-Z]{3}$/;

interface NewAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Prefilled currency, e.g. the statement's; empty to make the user type it. */
  defaultCurrency: string;
  onCreated: (account: Account) => void;
}

/** A small dialog to add the account a statement belongs to, without leaving the import. */
export function NewAccountDialog({
  open,
  onOpenChange,
  defaultCurrency,
  onCreated,
}: NewAccountDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New account</DialogTitle>
          <DialogDescription>The bank account or card this statement comes from.</DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so every opening starts with a fresh form. */}
        <NewAccountForm
          defaultCurrency={defaultCurrency}
          onCancel={() => {
            onOpenChange(false);
          }}
          onCreated={onCreated}
        />
      </DialogContent>
    </Dialog>
  );
}

interface NewAccountFormProps {
  defaultCurrency: string;
  onCancel: () => void;
  onCreated: (account: Account) => void;
}

function NewAccountForm({ defaultCurrency, onCancel, onCreated }: NewAccountFormProps) {
  const createAccount = useCreateAccount();
  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("checking");
  const [currency, setCurrency] = useState(defaultCurrency);
  const [submitted, setSubmitted] = useState(false);
  const ids = { name: useId(), type: useId(), currency: useId() };

  const nameError = name.trim() === "" ? "Enter a name, such as “Main Checking”." : null;
  const currencyError = CURRENCY_CODE.test(currency)
    ? null
    : "Enter a three-letter currency code, such as CAD or USD.";
  const showNameError = submitted && nameError !== null;
  const showCurrencyError = submitted && currencyError !== null;

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (nameError !== null || currencyError !== null || createAccount.isPending) return;
    createAccount.mutate({ name: name.trim(), type, currency }, { onSuccess: onCreated });
  }

  return (
    <form noValidate onSubmit={submit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.name}>Name</Label>
        <Input
          id={ids.name}
          value={name}
          maxLength={100}
          autoComplete="off"
          placeholder="Main Checking"
          aria-invalid={showNameError}
          aria-describedby={showNameError ? `${ids.name}-error` : undefined}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        {showNameError ? (
          <p id={`${ids.name}-error`} className="text-destructive text-sm">
            {nameError}
          </p>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.type}>Type</Label>
          <Select
            value={type}
            onValueChange={(value) => {
              setType(value as AccountType);
            }}
          >
            <SelectTrigger id={ids.type} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACCOUNT_TYPES.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.currency}>Currency</Label>
          <Input
            id={ids.currency}
            value={currency}
            maxLength={3}
            autoComplete="off"
            spellCheck={false}
            placeholder="CAD"
            className="uppercase placeholder:normal-case"
            aria-invalid={showCurrencyError}
            aria-describedby={showCurrencyError ? `${ids.currency}-error` : undefined}
            onChange={(event) => {
              setCurrency(event.target.value.toUpperCase().replace(/[^A-Z]/g, ""));
            }}
          />
          {showCurrencyError ? (
            <p id={`${ids.currency}-error`} className="text-destructive text-sm">
              {currencyError}
            </p>
          ) : null}
        </div>
      </div>

      {createAccount.isError ? (
        <Notice tone="error" title="The account couldn't be created">
          {errorMessage(createAccount.error)}
        </Notice>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={createAccount.isPending}>
          {createAccount.isPending ? (
            <LoaderCircle aria-hidden="true" className="animate-spin" />
          ) : null}
          Create account
        </Button>
      </DialogFooter>
    </form>
  );
}
