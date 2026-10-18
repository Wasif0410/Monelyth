import { Info, Pencil, Trash2 } from "lucide-react";
import {
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type SubmitEvent,
} from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import type { Account } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate, formatMoney } from "@/lib/format";
import { paths } from "@/paths";
import { accountTypeInfo, MAX_NAME_LENGTH } from "@/screens/accounts/accountTypes";
import { useUpdateAccount } from "@/screens/accounts/queries";
import { countOf } from "@/screens/accounts/text";

interface AccountCardProps {
  account: Account;
  onDelete: (account: Account) => void;
}

/** One account with its numbers, renamed in place. */
export function AccountCard({ account, onDelete }: AccountCardProps) {
  const [editing, setEditing] = useState(false);
  const editButton = useRef<HTMLButtonElement>(null);
  const { icon: Icon, label: typeLabel } = accountTypeInfo(account.type);

  function stopEditing() {
    setEditing(false);
    // Put focus back where the user started, once the button is rendered again.
    requestAnimationFrame(() => editButton.current?.focus());
  }

  return (
    <Card className="h-full" role="group" aria-label={account.name}>
      <CardContent className="flex h-full flex-col gap-5">
        <div className="flex items-start gap-3">
          <span className="bg-accent text-accent-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
            <Icon aria-hidden="true" className="size-5" />
          </span>

          {editing ? (
            <EditAccountForm account={account} onDone={stopEditing} />
          ) : (
            <>
              <div className="min-w-0 flex-1">
                <h2 className="truncate font-medium" title={account.name}>
                  {account.name}
                </h2>
                <p className="text-muted-foreground mt-0.5 truncate text-sm">
                  {[account.institution, typeLabel, account.currency]
                    .filter((part) => part !== null)
                    .join(" · ")}
                </p>
              </div>
              <div className="-mt-1 -mr-2 flex shrink-0">
                <IconButton
                  ref={editButton}
                  label={`Rename ${account.name}`}
                  tooltip="Rename"
                  onClick={() => {
                    setEditing(true);
                  }}
                >
                  <Pencil />
                </IconButton>
                <IconButton
                  label={`Delete ${account.name}`}
                  tooltip="Delete"
                  className="hover:text-destructive"
                  onClick={() => {
                    onDelete(account);
                  }}
                >
                  <Trash2 />
                </IconButton>
              </div>
            </>
          )}
        </div>

        {account.transaction_count > 0 ? (
          <AccountStats account={account} />
        ) : (
          <p className="text-muted-foreground mt-auto border-t pt-4 text-sm">
            No transactions yet.{" "}
            <Link
              to={paths.import}
              className="text-primary font-medium underline-offset-4 hover:underline"
            >
              Import a statement
            </Link>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Count, latest date and net, each a link to the transactions behind it where it's a number. */
function AccountStats({ account }: { account: Account }) {
  const transactions = transactionsOf(account);
  const net = formatMoney(account.net_amount_cents, account.currency);
  return (
    <dl className="mt-auto grid grid-cols-3 gap-3 border-t pt-4 text-sm">
      <Stat label="Transactions">
        <Link
          to={transactions}
          className="text-primary font-medium underline-offset-4 hover:underline"
          aria-label={`${countOf(account.transaction_count, "transaction")} in ${account.name}`}
        >
          {account.transaction_count.toLocaleString()}
        </Link>
      </Stat>
      <Stat label="Latest">
        {account.latest_transaction_date === null
          ? "—"
          : formatDate(account.latest_transaction_date)}
      </Stat>
      <Stat label={<NetLabel />}>
        <Link
          to={transactions}
          className="underline-offset-4 hover:underline"
          aria-label={`Net of imports for ${account.name}: ${net}`}
        >
          {net}
        </Link>
      </Stat>
    </dl>
  );
}

/** The Transactions screen filtered to this account. */
function transactionsOf(account: Account): string {
  return `${paths.transactions}?${new URLSearchParams({ account: String(account.id) }).toString()}`;
}

function Stat({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground flex items-center gap-1 text-xs">{label}</dt>
      <dd className="mt-1 truncate tabular-nums">{children}</dd>
    </div>
  );
}

function NetLabel() {
  return (
    <>
      Net of imports
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-full outline-none focus-visible:ring-[3px]"
            aria-label="About net of imports"
          >
            <Info aria-hidden="true" className="size-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-64">
          Money in minus money out across every imported transaction. It isn't the bank balance,
          which also includes what the account held before your first import.
        </TooltipContent>
      </Tooltip>
    </>
  );
}

interface IconButtonProps {
  ref?: Ref<HTMLButtonElement>;
  label: string;
  tooltip: string;
  className?: string;
  onClick: () => void;
  children: ReactNode;
}

function IconButton({ ref, label, tooltip, className, onClick, children }: IconButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          ref={ref}
          variant="ghost"
          size="icon-sm"
          aria-label={label}
          className={className}
          onClick={onClick}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

interface EditAccountFormProps {
  account: Account;
  onDone: () => void;
}

function EditAccountForm({ account, onDone }: EditAccountFormProps) {
  const updateAccount = useUpdateAccount();
  const [name, setName] = useState(account.name);
  const [institution, setInstitution] = useState(account.institution ?? "");
  const ids = { name: useId(), institution: useId() };

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextName = name.trim();
    const nextInstitution = institution.trim() || null;
    if (!nextName || updateAccount.isPending) return;
    if (nextName === account.name && nextInstitution === account.institution) {
      onDone();
      return;
    }
    updateAccount.mutate(
      { id: account.id, name: nextName, institution: nextInstitution },
      {
        onSuccess: (updated) => {
          toast.success(`Saved ${updated.name}`);
          onDone();
        },
      },
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape" && !updateAccount.isPending) {
      event.preventDefault();
      onDone();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      onKeyDown={handleKeyDown}
      aria-label={`Rename ${account.name}`}
      className="flex min-w-0 flex-1 flex-col gap-3"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.name}>Name</Label>
        <Input
          id={ids.name}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
          required
          autoFocus
          onFocus={(event) => {
            event.target.select();
          }}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.institution}>
          Institution <span className="text-muted-foreground font-normal">(optional)</span>
        </Label>
        <Input
          id={ids.institution}
          value={institution}
          onChange={(event) => {
            setInstitution(event.target.value);
          }}
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
        />
      </div>
      {updateAccount.isError ? (
        <p role="alert" className="text-destructive text-sm">
          {updateAccount.error.message}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!name.trim() || updateAccount.isPending}>
          {updateAccount.isPending ? "Saving…" : "Save"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={updateAccount.isPending}
          onClick={onDone}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
