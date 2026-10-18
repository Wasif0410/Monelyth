import { Plus } from "lucide-react";
import { useId } from "react";

import type { Account } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** The item that opens the new-account dialog instead of choosing an account. */
const NEW_ACCOUNT = "new";

interface AccountPickerProps {
  accounts: readonly Account[];
  value: number | null;
  onChange: (accountId: number) => void;
  onNewAccount: () => void;
  disabled: boolean;
}

/** Choose the account a statement belongs to, or start adding a new one. */
export function AccountPicker({
  accounts,
  value,
  onChange,
  onNewAccount,
  disabled,
}: AccountPickerProps) {
  const id = useId();

  if (accounts.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-muted-foreground text-sm">You haven't added any accounts yet.</p>
        <Button variant="outline" disabled={disabled} onClick={onNewAccount}>
          <Plus aria-hidden="true" />
          New account…
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>Import into</Label>
      <Select
        value={value === null ? "" : String(value)}
        disabled={disabled}
        onValueChange={(selected) => {
          if (selected === NEW_ACCOUNT) onNewAccount();
          else onChange(Number(selected));
        }}
      >
        <SelectTrigger id={id} className="w-full sm:w-80">
          <SelectValue placeholder="Choose an account" />
        </SelectTrigger>
        <SelectContent>
          {accounts.map((account) => (
            <SelectItem key={account.id} value={String(account.id)}>
              {account.name} <span className="text-muted-foreground">{account.currency}</span>
            </SelectItem>
          ))}
          <SelectSeparator />
          <SelectItem value={NEW_ACCOUNT}>
            <Plus aria-hidden="true" />
            New account…
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
