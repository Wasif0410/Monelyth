import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Month } from "@/screens/transactions/filters";
import { formatMonth, monthsBetween, shiftMonth } from "@/screens/transactions/months";

const ALL_TIME = "all";

interface MonthPickerProps {
  /** `null` for all time. */
  value: Month | null;
  onChange: (month: Month | null) => void;
  /** The months that have transactions. */
  first: Month;
  last: Month;
}

/**
 * Pick one month, or all time. The arrows step a month at a time within the months that have
 * transactions; from "All time", the left arrow goes to the latest month.
 */
export function MonthPicker({ value, onChange, first, last }: MonthPickerProps) {
  const months = monthsBetween(first, last);
  // A link can name a month without transactions; list it so it still shows.
  if (value !== null && !months.includes(value)) {
    months.push(value);
    months.sort().reverse();
  }

  const previous = value === null ? last : shiftMonth(value, -1);
  const next = value === null ? null : shiftMonth(value, 1);

  return (
    <div role="group" aria-label="Month" className="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon"
        aria-label="Previous month"
        disabled={previous < first}
        onClick={() => {
          onChange(previous);
        }}
      >
        <ChevronLeft aria-hidden="true" />
      </Button>
      <Select
        value={value ?? ALL_TIME}
        onValueChange={(month) => {
          onChange(month === ALL_TIME ? null : month);
        }}
      >
        <SelectTrigger aria-label="Month" className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" className="max-h-80">
          <SelectItem value={ALL_TIME}>All time</SelectItem>
          <SelectSeparator />
          {months.map((month) => (
            <SelectItem key={month} value={month}>
              {formatMonth(month)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="icon"
        aria-label="Next month"
        disabled={next === null || next > last}
        onClick={() => {
          if (next !== null) onChange(next);
        }}
      >
        <ChevronRight aria-hidden="true" />
      </Button>
    </div>
  );
}
