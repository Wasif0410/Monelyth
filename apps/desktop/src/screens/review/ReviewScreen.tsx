import { CheckCheck, Undo2 } from "lucide-react";
import { useEffect, useEffectEvent, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { useAccounts, useCategories } from "@/api/queries";
import { QueryError } from "@/components/QueryError";
import { ScreenHeader } from "@/components/ScreenHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/utils";
import { AcceptAllDialog } from "@/screens/review/AcceptAllDialog";
import { suggestionCount } from "@/screens/review/format";
import {
  useAcceptSuggestions,
  useReviewQueue,
  useReviewSummary,
  type Transaction,
} from "@/screens/review/queries";
import { ReviewCard } from "@/screens/review/ReviewCard";
import { groupCategories } from "@/screens/transactions/categoryGroups";
import { transactionCount } from "@/screens/transactions/format";
import { useSetCategory } from "@/screens/transactions/hooks";

/**
 * The review queue, one transaction at a time: accept the suggestion (A), choose another
 * category (C) or skip it for now (S).
 */
export function ReviewScreen() {
  const accounts = useAccounts();
  const categories = useCategories();
  const queue = useReviewQueue();
  const summary = useReviewSummary();
  const accept = useAcceptSuggestions();
  const { mutate: setCategory } = useSetCategory();
  const [skipped, setSkipped] = useState<ReadonlySet<number>>(new Set());
  // Answered here but possibly still in the loaded queue until it refreshes.
  const [answered, setAnswered] = useState<ReadonlySet<number>>(new Set());
  const [choosing, setChoosing] = useState(false);
  const [confirmingAll, setConfirmingAll] = useState(false);

  const accountsById = useMemo(
    () => new Map((accounts.data ?? []).map((account) => [account.id, account])),
    [accounts.data],
  );
  const categoryGroups = useMemo(() => groupCategories(categories.data ?? []), [categories.data]);
  const categoryNames = useMemo(
    () => new Map((categories.data ?? []).map((category) => [category.id, category.name])),
    [categories.data],
  );

  const items = queue.data?.items ?? [];
  const waiting = Math.max(
    0,
    (queue.data?.total ?? 0) - items.filter((tx) => answered.has(tx.id)).length,
  );
  const current = items.find((tx) => !answered.has(tx.id) && !skipped.has(tx.id));

  function markAnswered(tx: Transaction, answeredNow: boolean) {
    setAnswered((previous) => {
      const next = new Set(previous);
      if (answeredNow) next.add(tx.id);
      else next.delete(tx.id);
      return next;
    });
  }

  function acceptCurrent() {
    if (current === undefined || current.category_id === null) return;
    const tx = current;
    markAnswered(tx, true);
    accept.mutate([tx.id], {
      onError: (error) => {
        markAnswered(tx, false);
        toast.error("Couldn't accept the suggestion", { description: errorMessage(error) });
      },
    });
  }

  function chooseForCurrent(categoryId: number) {
    if (current === undefined) return;
    const tx = current;
    setChoosing(false);
    markAnswered(tx, true);
    // On failure useSetCategory says why in a toast; the transaction comes back to review.
    setCategory(
      { transaction: tx, categoryId },
      {
        onError: () => {
          markAnswered(tx, false);
        },
      },
    );
  }

  function skipCurrent() {
    if (current === undefined) return;
    const tx = current;
    setSkipped((previous) => new Set(previous).add(tx.id));
  }

  const onShortcut = useEffectEvent((event: KeyboardEvent) => {
    if (current === undefined || confirmingAll || !isShortcutTarget(event)) return;
    const key = event.key.toLowerCase();
    if (key === "a") acceptCurrent();
    else if (key === "c") setChoosing(true);
    else if (key === "s") skipCurrent();
    else return;
    event.preventDefault();
  });
  useEffect(() => {
    window.addEventListener("keydown", onShortcut);
    return () => {
      window.removeEventListener("keydown", onShortcut);
    };
  }, []);

  const withSuggestion = summary.data?.with_suggestion ?? 0;
  const header = (
    <ScreenHeader
      title="Review"
      description="Transactions Monelyth wasn't sure about. What you decide is remembered for the merchant."
      actions={
        withSuggestion > 0 ? (
          <Button
            variant="outline"
            onClick={() => {
              setConfirmingAll(true);
            }}
          >
            <CheckCheck aria-hidden="true" />
            Accept all {suggestionCount(withSuggestion)}
          </Button>
        ) : undefined
      }
    />
  );

  const setup = [accounts, categories, queue];
  const failed = setup.find((query) => query.isError);
  let content: ReactNode;
  if (failed) {
    content = (
      <QueryError
        error={failed.error}
        onRetry={() => {
          for (const query of setup) if (query.isError) void query.refetch();
        }}
      />
    );
  } else if (!accounts.data || !categories.data || !queue.data) {
    content = <CardSkeleton />;
  } else if (current !== undefined) {
    content = (
      <div className="flex flex-col gap-3">
        <p className="text-muted-foreground text-sm" aria-live="polite">
          {transactionCount(waiting)} waiting
          {skipped.size > 0 ? `, ${String(skipped.size)} skipped` : ""}
        </p>
        <ReviewCard
          // A fresh card per transaction, so focus and the open list never carry over.
          key={current.id}
          transaction={current}
          account={accountsById.get(current.account_id)}
          categoryGroups={categoryGroups}
          categoryNames={categoryNames}
          choosing={choosing}
          onChoosingChange={setChoosing}
          onAccept={acceptCurrent}
          onChoose={chooseForCurrent}
          onSkip={skipCurrent}
        />
        <p className="text-muted-foreground text-xs">
          Keyboard: <kbd className="font-sans font-medium">A</kbd> accept,{" "}
          <kbd className="font-sans font-medium">C</kbd> choose a category,{" "}
          <kbd className="font-sans font-medium">S</kbd> skip.
        </p>
      </div>
    );
  } else if (skipped.size > 0 && waiting > 0) {
    content = (
      <StateCard
        title="That's all for now"
        description={`You skipped ${transactionCount(skipped.size)}. They wait here until you're ready.`}
        action={
          <Button
            variant="outline"
            onClick={() => {
              setSkipped(new Set());
            }}
          >
            <Undo2 aria-hidden="true" />
            Review the skipped ones
          </Button>
        }
      />
    );
  } else if (waiting > 0 || queue.isFetching) {
    // Everything loaded was answered; the next ones are on their way.
    content = <CardSkeleton />;
  } else {
    content = (
      <StateCard
        title="All caught up"
        description="Nothing needs review. When Monelyth isn't sure about a new transaction, it shows up here."
      />
    );
  }

  return (
    <>
      {header}
      <div className="flex max-w-3xl flex-col gap-4">{content}</div>
      <AcceptAllDialog
        open={confirmingAll}
        count={withSuggestion}
        onOpenChange={setConfirmingAll}
      />
    </>
  );
}

/** Shortcuts apply unless the user is typing, choosing from a list or in a dialog. */
function isShortcutTarget(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.repeat) return false;
  if (event.ctrlKey || event.metaKey || event.altKey) return false;
  const target = event.target;
  if (!(target instanceof Element)) return true;
  return (
    target.closest(
      "input, textarea, [contenteditable], [role=listbox], [role=dialog], [role=alertdialog]",
    ) === null
  );
}

function StateCard({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 px-6 py-14 text-center">
        <span className="bg-accent text-accent-foreground flex size-12 items-center justify-center rounded-full">
          <CheckCheck aria-hidden="true" className="size-6" />
        </span>
        <div>
          <h2 className="font-medium">{title}</h2>
          <p className="text-muted-foreground mt-1 max-w-sm text-sm">{description}</p>
        </div>
        {action}
      </CardContent>
    </Card>
  );
}

function CardSkeleton() {
  return (
    <Card role="status" aria-label="Loading the review queue">
      <CardContent className="flex flex-col gap-6 p-6">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-80" />
        </div>
        <Skeleton className="h-12 w-full" />
        <div className="flex gap-2">
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-9 w-24" />
        </div>
      </CardContent>
    </Card>
  );
}
