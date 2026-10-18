import { Check, SkipForward } from "lucide-react";
import type { ReactNode } from "react";

import type { Account } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { suggestionOrigin } from "@/screens/review/format";
import type { Transaction } from "@/screens/review/queries";
import type { CategoryGroup } from "@/screens/transactions/categoryGroups";

interface ReviewCardProps {
  transaction: Transaction;
  account: Account | undefined;
  categoryGroups: readonly CategoryGroup[];
  categoryNames: ReadonlyMap<number, string>;
  /** Whether the category list is open (it also opens with the C key). */
  choosing: boolean;
  onChoosingChange: (open: boolean) => void;
  onAccept: () => void;
  onChoose: (categoryId: number) => void;
  onSkip: () => void;
}

/** One transaction waiting for review, with what Monelyth suggests and the ways to answer. */
export function ReviewCard({
  transaction: tx,
  account,
  categoryGroups,
  categoryNames,
  choosing,
  onChoosingChange,
  onAccept,
  onChoose,
  onSkip,
}: ReviewCardProps) {
  const name = tx.merchant ?? tx.description_raw;
  const suggested = tx.category_id === null ? undefined : categoryNames.get(tx.category_id);
  const moneyIn = tx.amount_cents > 0;

  return (
    <Card>
      <CardContent className="flex flex-col gap-6 p-6">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <p className="text-muted-foreground text-sm">
              {formatDate(tx.posted_date)}
              {account ? ` · ${account.name}` : null}
            </p>
            <h2 className="mt-1 truncate text-xl font-semibold tracking-tight" title={name}>
              {name}
            </h2>
            {tx.merchant !== null ? (
              <p
                className="text-muted-foreground mt-0.5 truncate text-sm"
                title={tx.description_raw}
              >
                {tx.description_raw}
              </p>
            ) : null}
          </div>
          {account ? (
            <p
              className={cn(
                "shrink-0 text-xl font-semibold tabular-nums",
                moneyIn && "text-success",
              )}
            >
              {moneyIn ? "+" : ""}
              {formatMoney(tx.amount_cents, account.currency)}
            </p>
          ) : null}
        </div>

        <div className="bg-muted/60 rounded-lg px-4 py-3">
          {suggested !== undefined && tx.category_source !== null ? (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="text-muted-foreground">Suggested</span>
              <Badge variant="outline" className="bg-card text-sm">
                {suggested}
              </Badge>
              <span className="text-muted-foreground">
                {suggestionOrigin(tx.category_source, tx.confidence)}
              </span>
            </p>
          ) : (
            <p className="text-muted-foreground text-sm">
              No suggestion: Monelyth doesn't know this one yet. Choose a category.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={onAccept} disabled={suggested === undefined} aria-keyshortcuts="A">
            <Check aria-hidden="true" />
            Accept
            <Shortcut>A</Shortcut>
          </Button>
          <Select
            open={choosing}
            onOpenChange={onChoosingChange}
            value=""
            onValueChange={(value) => {
              const categoryId = Number(value);
              if (Number.isSafeInteger(categoryId)) onChoose(categoryId);
            }}
          >
            <SelectTrigger
              aria-label={`Choose a category for ${name}`}
              aria-keyshortcuts="C"
              className="w-56"
            >
              <SelectValue placeholder="Choose a category…" />
              <Shortcut>C</Shortcut>
            </SelectTrigger>
            <SelectContent position="popper" align="start" className="max-h-80">
              {categoryGroups.map((group) => (
                <SelectGroup key={group.label}>
                  <SelectLabel>{group.label}</SelectLabel>
                  {group.categories.map((category) => (
                    <SelectItem key={category.id} value={String(category.id)}>
                      {category.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
          <Button variant="ghost" onClick={onSkip} aria-keyshortcuts="S">
            <SkipForward aria-hidden="true" />
            Skip
            <Shortcut>S</Shortcut>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** A key hint inside a button; hidden from screen readers, which announce `aria-keyshortcuts`. */
function Shortcut({ children }: { children: ReactNode }) {
  return (
    <kbd
      aria-hidden="true"
      className="border-current/25 ml-1 rounded border px-1 font-sans text-[0.6875rem] leading-4 opacity-70"
    >
      {children}
    </kbd>
  );
}
