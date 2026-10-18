import { useQueryClient } from "@tanstack/react-query";
import { FileText, LoaderCircle } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { ApiError } from "@/api/client";
import { queryKeys, useAccounts, type Account } from "@/api/queries";
import { QueryError } from "@/components/QueryError";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, errorMessage } from "@/lib/utils";
import { AccountPicker } from "@/screens/import/AccountPicker";
import {
  useCommitImport,
  useImportPreview,
  type ImportPreview,
  type ImportResult,
  type StatementSelection,
} from "@/screens/import/api";
import { formatTimestampDate, joinAnd, plural } from "@/screens/import/display";
import { FileInputButton } from "@/screens/import/FileInputButton";
import {
  choicesFromDraft,
  missingParts,
  sameChoices,
  toLayout,
  type LayoutChoices,
} from "@/screens/import/layout";
import { LayoutPanel } from "@/screens/import/LayoutPanel";
import { NewAccountDialog } from "@/screens/import/NewAccountDialog";
import { Notice } from "@/screens/import/Notice";
import { PreviewTable } from "@/screens/import/PreviewTable";

const FORMAT_LABELS: Record<ImportPreview["format"], string> = { csv: "CSV", ofx: "OFX" };

interface ReviewImportProps {
  selection: StatementSelection;
  /** The user picked a different file. */
  onFiles: (files: File[]) => void;
  onImported: (result: ImportResult, account: Account) => void;
}

/**
 * Everything between choosing a file and importing it: what the file holds, how a CSV is laid
 * out, and which account it goes into. Keyed by the selection, so a new file starts afresh.
 */
export function ReviewImport({ selection, onFiles, onImported }: ReviewImportProps) {
  const detection = useImportPreview(selection, null);
  const preview = detection.data;

  if (detection.isPending) {
    return (
      <div aria-busy="true" className="flex flex-col gap-6">
        <FileCard name={selection.file.name} onFiles={onFiles} busy={false}>
          <span className="flex items-center gap-1.5">
            <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
            Reading the file…
          </span>
        </FileCard>
        <Card>
          <CardContent className="flex flex-col gap-3">
            <Skeleton className="h-5 w-32" />
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (preview === undefined) {
    return (
      <div className="flex flex-col gap-6">
        <FileCard name={selection.file.name} onFiles={onFiles} busy={false} />
        <Notice
          tone="error"
          title="Monelyth couldn't read this file"
          actions={
            <FileInputButton size="sm" onFiles={onFiles}>
              Choose another file
            </FileInputButton>
          }
        >
          {errorMessage(detection.error)}
        </Notice>
      </div>
    );
  }

  return (
    <Review selection={selection} preview={preview} onFiles={onFiles} onImported={onImported} />
  );
}

interface ReviewProps extends ReviewImportProps {
  /** The engine's first reading of the file, with the layout it detected or remembered. */
  preview: ImportPreview;
}

function Review({ selection, preview, onFiles, onImported }: ReviewProps) {
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const commit = useCommitImport();
  const [editedChoices, setEditedChoices] = useState<LayoutChoices | null>(null);
  const [chosenAccountId, setChosenAccountId] = useState<number | null>(null);
  const [newAccountOpen, setNewAccountOpen] = useState(false);

  // Layout: start from what the engine detected (or remembered), then the user's changes.
  const csv = preview.csv;
  const detectedChoices = useMemo(() => (csv ? choicesFromDraft(csv.layout) : null), [csv]);
  const choices = editedChoices ?? detectedChoices;
  const layout = csv && choices ? toLayout(csv.layout, choices) : null;
  const edited =
    editedChoices !== null &&
    detectedChoices !== null &&
    !sameChoices(editedChoices, detectedChoices);
  const chosen = useImportPreview(selection, edited ? layout : null, {
    enabled: edited && layout !== null,
  });
  // The rows to show: none while the layout is incomplete, a re-reading once the user has
  // changed it, and otherwise the first reading.
  const incomplete = csv !== null && layout === null;
  const rowsQuery = !incomplete && edited ? chosen : null;
  const rows = incomplete ? undefined : rowsQuery ? rowsQuery.data : preview;
  const updating = rowsQuery !== null && (rowsQuery.isPlaceholderData || rowsQuery.isFetching);
  const rowsError = rowsQuery?.isError ? rowsQuery.error : null;

  // Account: the user's choice, or the only account there is.
  const accountList = accounts.data ?? [];
  const account =
    accountList.find((candidate) => candidate.id === chosenAccountId) ??
    (accountList.length === 1 ? accountList[0] : undefined);
  const currencyMismatch =
    preview.currency !== null && account !== undefined && account.currency !== preview.currency;
  const currency = preview.currency ?? account?.currency ?? null;

  const transactionCount = rows && !updating && rowsError === null ? rows.transaction_count : null;
  const blocked = preview.previous_import !== null || currencyMismatch;
  const canImport =
    transactionCount !== null && account !== undefined && !blocked && !commit.isPending;

  function changeLayout(next: LayoutChoices) {
    commit.reset();
    setEditedChoices(next);
  }

  function chooseAccount(accountId: number) {
    commit.reset();
    setChosenAccountId(accountId);
  }

  function addCreatedAccount(created: Account) {
    // Show the new account at once; the refetch that useCreateAccount starts confirms it.
    queryClient.setQueryData<Account[]>(queryKeys.accounts, (current = []) =>
      current.some((existing) => existing.id === created.id) ? current : [...current, created],
    );
    chooseAccount(created.id);
    setNewAccountOpen(false);
  }

  function startImport() {
    if (!canImport) return;
    commit.mutate(
      { file: selection.file, accountId: account.id, layout: csv ? layout : null },
      {
        onSuccess: (result) => {
          onImported(result, account);
        },
      },
    );
  }

  const previous = preview.previous_import;
  const previousAccount = accountList.find((candidate) => candidate.id === previous?.account_id);

  return (
    <div className="flex flex-col gap-6">
      <FileCard name={preview.file_name} onFiles={onFiles} busy={commit.isPending}>
        <Badge variant="secondary">{FORMAT_LABELS[preview.format]}</Badge>
        {transactionCount === null ? null : <span>{plural(transactionCount, "transaction")}</span>}
      </FileCard>

      {previous ? (
        <Notice
          tone="warning"
          title={`You imported this file on ${formatTimestampDate(previous.imported_at)}`}
        >
          {previousAccount ? `It went into ${previousAccount.name}. ` : null}
          Importing it again would add nothing, so it can't be imported twice. If your bank has
          newer transactions, download a fresh statement and import that.
        </Notice>
      ) : null}

      {csv && choices ? (
        <LayoutPanel
          csv={csv}
          choices={choices}
          onChange={changeLayout}
          disabled={commit.isPending}
        />
      ) : null}

      <Card className="overflow-hidden">
        <CardContent className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-base font-semibold">Preview</h2>
          {rows && rowsError === null ? (
            <p className="text-muted-foreground text-sm">
              {previewCaption(rows.rows.length, rows.transaction_count)}
            </p>
          ) : null}
        </CardContent>
        <PreviewBody
          rows={rows}
          error={rowsError}
          updating={updating}
          missing={choices ? missingParts(choices) : []}
          currency={currency}
        />
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-4">
          <div>
            <h2 className="text-base font-semibold">Account</h2>
            <p className="text-muted-foreground mt-1 text-sm">
              Which account or card is this statement from?
            </p>
          </div>
          {accounts.isPending ? (
            <Skeleton aria-label="Loading accounts" className="h-9 w-full sm:w-80" />
          ) : accounts.isError ? (
            <QueryError
              error={accounts.error}
              onRetry={() => {
                void accounts.refetch();
              }}
            />
          ) : (
            <AccountPicker
              accounts={accountList}
              value={account?.id ?? null}
              onChange={chooseAccount}
              onNewAccount={() => {
                setNewAccountOpen(true);
              }}
              disabled={commit.isPending}
            />
          )}

          {currencyMismatch ? (
            <Notice tone="warning" title="This account uses a different currency">
              This statement is in {preview.currency}, but {account.name} uses {account.currency}.
              Choose an account in {preview.currency}, or add one.
            </Notice>
          ) : null}

          {commit.isError ? (
            <Notice tone="error" title="The file wasn't imported">
              {errorMessage(commit.error)}
            </Notice>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-3 border-t pt-4">
            <p role="status" aria-live="polite" className="text-muted-foreground mr-auto text-sm">
              {commit.isPending ? "Importing… This takes a moment for large statements." : null}
            </p>
            <Button size="lg" disabled={!canImport} onClick={startImport}>
              {commit.isPending ? (
                <>
                  <LoaderCircle aria-hidden="true" className="animate-spin" />
                  Importing…
                </>
              ) : transactionCount === null ? (
                "Import"
              ) : (
                `Import ${plural(transactionCount, "transaction")}`
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      <NewAccountDialog
        open={newAccountOpen}
        onOpenChange={setNewAccountOpen}
        defaultCurrency={preview.currency ?? account?.currency ?? accountList[0]?.currency ?? ""}
        onCreated={addCreatedAccount}
      />
    </div>
  );
}

interface FileCardProps {
  name: string;
  onFiles: (files: File[]) => void;
  busy: boolean;
  /** Facts about the file, shown under its name. */
  children?: ReactNode;
}

function FileCard({ name, onFiles, busy, children }: FileCardProps) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-4">
        <div className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg">
          <FileText aria-hidden="true" className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium" title={name}>
            {name}
          </p>
          <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-2 text-sm">
            {children}
          </div>
        </div>
        <FileInputButton variant="outline" size="sm" disabled={busy} onFiles={onFiles}>
          Choose another file
        </FileInputButton>
      </CardContent>
    </Card>
  );
}

interface PreviewBodyProps {
  rows: ImportPreview | undefined;
  error: unknown;
  updating: boolean;
  missing: readonly string[];
  currency: string | null;
}

function PreviewBody({ rows, error, updating, missing, currency }: PreviewBodyProps) {
  if (error !== null) {
    const misfit = error instanceof ApiError && error.status === 422;
    return (
      <div className="px-5 pb-5">
        <Notice
          tone="error"
          title={misfit ? "These choices don't fit the file" : "The preview couldn't be updated"}
        >
          {errorMessage(error)}
        </Notice>
      </div>
    );
  }
  if (rows === undefined) {
    if (missing.length > 0) {
      return (
        <p className="text-muted-foreground px-5 pb-5 text-sm">
          Choose {joinAnd(missing)} above to see the transactions.
        </p>
      );
    }
    return (
      <div aria-busy="true" className="flex flex-col gap-3 px-5 pb-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-9 w-full" />
        ))}
      </div>
    );
  }
  return (
    <div
      aria-busy={updating}
      className={cn("border-t transition-opacity", updating && "opacity-50")}
    >
      <PreviewTable
        rows={rows.rows}
        currency={currency}
        caption={previewCaption(rows.rows.length, rows.transaction_count)}
      />
      {rows.warnings.length > 0 ? (
        <ul aria-label="Notes about this file" className="flex flex-col gap-1.5 border-t px-5 py-4">
          {rows.warnings.map((warning, index) => (
            <li key={`${String(index)}-${warning}`} className="text-muted-foreground text-sm">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function previewCaption(shown: number, total: number | null): string {
  if (total === null) return `The first ${plural(shown, "row")} Monelyth could read`;
  if (total === shown) return `All ${plural(total, "transaction")}`;
  return `The first ${String(shown)} of ${plural(total, "transaction")}`;
}
