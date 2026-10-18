import { CircleAlert, Search, X } from "lucide-react";
import { useEffect, useEffectEvent, useState } from "react";

import type { Account } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { CategoryGroup } from "@/screens/transactions/categoryGroups";
import {
  hasActiveFilters,
  MAX_SEARCH_LENGTH,
  NO_FILTERS,
  UNCATEGORIZED,
  type Month,
  type TransactionFilters,
} from "@/screens/transactions/filters";
import { MonthPicker } from "@/screens/transactions/MonthPicker";
import { transactionCount } from "@/screens/transactions/format";

/** How long typing must pause before the search runs. */
export const SEARCH_DEBOUNCE_MS = 300;

const ANY = "any";

interface TransactionsToolbarProps {
  filters: TransactionFilters;
  onChange: (next: TransactionFilters, options?: { replace?: boolean }) => void;
  accounts: readonly Account[];
  categoryGroups: readonly CategoryGroup[];
  /** The months that have transactions. */
  months: { first: Month; last: Month };
  /** How many transactions match, once known. */
  total: number | undefined;
}

export function TransactionsToolbar({
  filters,
  onChange,
  accounts,
  categoryGroups,
  months,
  total,
}: TransactionsToolbarProps) {
  const update = (changes: Partial<TransactionFilters>) => {
    onChange({ ...filters, ...changes });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchBox
        value={filters.search}
        onSearch={(search) => {
          // Each keystroke pause shouldn't become a history entry of its own.
          onChange({ ...filters, search }, { replace: true });
        }}
      />

      <Select
        value={filters.accountId === null ? ANY : String(filters.accountId)}
        onValueChange={(value) => {
          update({ accountId: value === ANY ? null : Number(value) });
        }}
      >
        <SelectTrigger aria-label="Account" className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper">
          <SelectItem value={ANY}>All accounts</SelectItem>
          {accounts.length > 0 ? <SelectSeparator /> : null}
          {accounts.map((account) => (
            <SelectItem key={account.id} value={String(account.id)}>
              {account.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <MonthPicker
        value={filters.month}
        onChange={(month) => {
          update({ month });
        }}
        first={months.first}
        last={months.last}
      />

      <Select
        value={filters.category === null ? ANY : String(filters.category)}
        onValueChange={(value) => {
          update({
            category:
              value === ANY ? null : value === UNCATEGORIZED ? UNCATEGORIZED : Number(value),
          });
        }}
      >
        <SelectTrigger aria-label="Category" className="w-48">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" className="max-h-80">
          <SelectItem value={ANY}>All categories</SelectItem>
          <SelectItem value={UNCATEGORIZED}>Uncategorized</SelectItem>
          {categoryGroups.map((group) => (
            <SelectGroup key={group.label}>
              <SelectSeparator />
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

      <Button
        variant="outline"
        aria-pressed={filters.needsReview}
        onClick={() => {
          update({ needsReview: !filters.needsReview });
        }}
        className={cn(
          filters.needsReview &&
            "border-warning/60 bg-warning/10 hover:bg-warning/15 dark:border-warning/50 dark:bg-warning/15 dark:hover:bg-warning/20",
        )}
      >
        <CircleAlert aria-hidden="true" className={cn(filters.needsReview && "text-warning")} />
        Needs review
      </Button>

      {hasActiveFilters(filters) ? (
        <Button
          variant="ghost"
          onClick={() => {
            onChange(NO_FILTERS);
          }}
        >
          <X aria-hidden="true" />
          Clear filters
        </Button>
      ) : null}

      <p aria-live="polite" className="text-muted-foreground ml-auto text-sm tabular-nums">
        {total === undefined ? null : transactionCount(total)}
      </p>
    </div>
  );
}

interface SearchBoxProps {
  /** The search in effect (from the URL). */
  value: string;
  onSearch: (search: string) => void;
}

/** A search field that applies what was typed once typing pauses. */
function SearchBox({ value, onSearch }: SearchBoxProps) {
  const [draft, setDraft] = useState(value);
  const [applied, setApplied] = useState(value);
  // The search can also change from outside (Clear filters, Back, a link): show it, unless
  // it only differs from what is typed by spaces the URL leaves out.
  if (value !== applied) {
    setApplied(value);
    if (draft.trim() !== value.trim()) setDraft(value);
  }

  const search = useEffectEvent((text: string) => {
    onSearch(text);
  });
  useEffect(() => {
    if (draft.trim() === value.trim()) return;
    const timer = window.setTimeout(() => {
      search(draft);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [draft, value]);

  return (
    <div className="relative w-64">
      <Search
        aria-hidden="true"
        className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
      />
      <Input
        type="search"
        aria-label="Search transactions"
        placeholder="Search merchants and descriptions"
        maxLength={MAX_SEARCH_LENGTH}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        className="pl-9"
      />
    </div>
  );
}
