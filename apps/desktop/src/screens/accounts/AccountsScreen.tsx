import { Landmark, Plus } from "lucide-react";
import { useState } from "react";

import { useAccounts, type Account } from "@/api/queries";
import { QueryError } from "@/components/QueryError";
import { ScreenHeader } from "@/components/ScreenHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AccountCard } from "@/screens/accounts/AccountCard";
import { AddAccountDialog } from "@/screens/accounts/AddAccountDialog";
import { DeleteAccountDialog } from "@/screens/accounts/DeleteAccountDialog";

export function AccountsScreen() {
  const accounts = useAccounts();
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<Account | null>(null);

  const hasAccounts = accounts.isSuccess && accounts.data.length > 0;
  const startAdding = () => {
    setAdding(true);
  };

  return (
    <>
      <ScreenHeader
        title="Accounts"
        description="The bank accounts and cards you import statements for."
        actions={
          hasAccounts ? (
            <Button onClick={startAdding}>
              <Plus aria-hidden="true" />
              Add account
            </Button>
          ) : undefined
        }
      />

      {accounts.isPending ? (
        <LoadingCards />
      ) : accounts.isError ? (
        <QueryError error={accounts.error} onRetry={() => void accounts.refetch()} />
      ) : accounts.data.length === 0 ? (
        <EmptyState onAdd={startAdding} />
      ) : (
        <ul aria-label="Accounts" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {accounts.data.map((account) => (
            <li key={account.id}>
              <AccountCard account={account} onDelete={setDeleting} />
            </li>
          ))}
        </ul>
      )}

      <AddAccountDialog
        open={adding}
        onOpenChange={setAdding}
        // New accounts most likely share the currency of the ones already there.
        defaultCurrency={accounts.data?.at(-1)?.currency ?? "CAD"}
      />
      <DeleteAccountDialog
        account={deleting}
        onClose={() => {
          setDeleting(null);
        }}
      />
    </>
  );
}

function LoadingCards() {
  return (
    <div
      role="status"
      aria-label="Loading accounts"
      className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
    >
      {[0, 1, 2].map((key) => (
        <Card key={key}>
          <CardContent className="flex flex-col gap-5">
            <div className="flex items-center gap-3">
              <Skeleton className="size-10 rounded-lg" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            </div>
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 px-6 py-14 text-center">
        <span className="bg-accent text-accent-foreground flex size-12 items-center justify-center rounded-xl">
          <Landmark aria-hidden="true" className="size-6" />
        </span>
        <div>
          <h2 className="font-medium">No accounts yet</h2>
          <p className="text-muted-foreground mt-1 max-w-sm text-sm">
            Add the bank accounts and cards you have statements for. Each import goes into one of
            them.
          </p>
        </div>
        <Button onClick={onAdd}>
          <Plus aria-hidden="true" />
          Add account
        </Button>
      </CardContent>
    </Card>
  );
}
