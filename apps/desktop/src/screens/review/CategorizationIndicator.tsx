import { CircleAlert, LoaderCircle } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCategorizationStatus } from "@/screens/review/queries";

const countFormat = new Intl.NumberFormat();

/**
 * A small note in the sidebar while transactions are categorized in the background, or when
 * the last run had a problem. Nothing at all otherwise.
 */
export function CategorizationIndicator() {
  const { data: status } = useCategorizationStatus();
  if (status === undefined) return null;

  const busy = status.state !== "idle";
  // A run with nothing to do is over before anyone could read about it.
  if (busy && status.total > 0) {
    return (
      <div role="status" className="flex flex-col gap-1.5 px-5 pb-1">
        <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <LoaderCircle aria-hidden="true" className="size-3.5 shrink-0 animate-spin" />
          Categorizing {countFormat.format(status.processed)} of {countFormat.format(status.total)}…
        </p>
        <div
          role="progressbar"
          aria-label="Categorizing transactions"
          aria-valuemin={0}
          aria-valuemax={status.total}
          aria-valuenow={status.processed}
          className="bg-accent h-1 overflow-hidden rounded-full"
        >
          <div
            className="bg-primary h-full rounded-full transition-[width]"
            style={{ width: `${String((status.processed / status.total) * 100)}%` }}
          />
        </div>
      </div>
    );
  }
  if (!busy && status.last_error !== null) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground mx-5 flex items-center gap-1.5 rounded-sm text-left text-xs"
          >
            <CircleAlert aria-hidden="true" className="text-warning size-3.5 shrink-0" />
            Categorization had a problem
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-72">
          {status.last_error}
        </TooltipContent>
      </Tooltip>
    );
  }
  return null;
}
