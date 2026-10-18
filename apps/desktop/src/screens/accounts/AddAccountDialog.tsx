import { useId, useState, type SubmitEvent } from "react";
import { toast } from "sonner";

import { useCreateAccount } from "@/api/queries";
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
import {
  ACCOUNT_TYPES,
  CURRENCIES,
  MAX_NAME_LENGTH,
  type AccountType,
} from "@/screens/accounts/accountTypes";

interface AddAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Preselected currency, e.g. the one the user's other accounts use. */
  defaultCurrency: string;
}

export function AddAccountDialog({ open, onOpenChange, defaultCurrency }: AddAccountDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add account</DialogTitle>
          <DialogDescription>
            A bank account or card you'll import statements for.
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so every opening starts with a blank form. */}
        <AddAccountForm
          defaultCurrency={defaultCurrency}
          onDone={() => {
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

interface AddAccountFormProps {
  defaultCurrency: string;
  onDone: () => void;
}

function AddAccountForm({ defaultCurrency, onDone }: AddAccountFormProps) {
  const createAccount = useCreateAccount();
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState("");
  const [type, setType] = useState<AccountType>("checking");
  const [currency, setCurrency] = useState(
    CURRENCIES.includes(defaultCurrency) ? defaultCurrency : "CAD",
  );
  const ids = {
    name: useId(),
    institution: useId(),
    type: useId(),
    currency: useId(),
    error: useId(),
  };

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || createAccount.isPending) return;
    createAccount.mutate(
      { name: trimmed, institution: institution.trim() || null, type, currency },
      {
        onSuccess: (account) => {
          toast.success(`Added ${account.name}`);
          onDone();
        },
      },
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4"
      aria-describedby={createAccount.isError ? ids.error : undefined}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.name}>Name</Label>
        <Input
          id={ids.name}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
          placeholder="e.g. Main Checking"
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
          required
          autoFocus
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.institution}>
          Institution <span className="text-muted-foreground font-normal">(optional)</span>
        </Label>
        <Input
          id={ids.institution}
          value={institution}
          onChange={(event) => {
            setInstitution(event.target.value);
          }}
          placeholder="e.g. TD, RBC, Chase"
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.type}>Type</Label>
          <Select
            value={type}
            onValueChange={(value) => {
              const next = ACCOUNT_TYPES.find((option) => option.value === value);
              if (next) setType(next.value);
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
          <Select value={currency} onValueChange={setCurrency}>
            <SelectTrigger id={ids.currency} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CURRENCIES.map((code) => (
                <SelectItem key={code} value={code}>
                  {code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {createAccount.isError ? (
        <p id={ids.error} role="alert" className="text-destructive text-sm">
          {createAccount.error.message}
        </p>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={!name.trim() || createAccount.isPending}>
          {createAccount.isPending ? "Adding…" : "Add account"}
        </Button>
      </DialogFooter>
    </form>
  );
}
