import { CircleAlert } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { CategoryGroup } from "@/screens/transactions/categoryGroups";
import type { Transaction } from "@/screens/transactions/hooks";

interface CategorySelectProps {
  transaction: Transaction;
  /** Shown in the trigger's accessible name, e.g. "Category for Loblaws". */
  label: string;
  groups: readonly CategoryGroup[];
  onChange: (categoryId: number) => void;
}

/** The category of one row, changed in place: one click (or Enter) opens it, a choice saves. */
export function CategorySelect({ transaction, label, groups, onChange }: CategorySelectProps) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Select
        // An empty value shows the placeholder.
        value={transaction.category_id === null ? "" : String(transaction.category_id)}
        onValueChange={(value) => {
          const categoryId = Number(value);
          if (Number.isSafeInteger(categoryId)) onChange(categoryId);
        }}
      >
        <SelectTrigger
          size="sm"
          aria-label={`Category for ${label}`}
          className="hover:border-input data-[state=open]:border-input w-full min-w-0 border-transparent bg-transparent shadow-none dark:bg-transparent"
        >
          <SelectValue placeholder="Uncategorized" />
        </SelectTrigger>
        <SelectContent position="popper" align="start" className="max-h-80">
          {groups.map((group) => (
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
      {transaction.needs_review ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <CircleAlert
              role="img"
              aria-label="Needs review"
              className="text-warning size-4 shrink-0"
            />
          </TooltipTrigger>
          <TooltipContent>Needs review: check this category</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}
