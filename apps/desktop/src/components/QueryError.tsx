import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/utils";

interface QueryErrorProps {
  error: unknown;
  /** Shown as a "Try again" button when given. */
  onRetry?: () => void;
}

/** Inline message for data that failed to load. */
export function QueryError({ error, onRetry }: QueryErrorProps) {
  return (
    <div
      role="alert"
      className="border-destructive/30 bg-destructive/5 flex items-start gap-3 rounded-lg border p-4"
    >
      <CircleAlert aria-hidden="true" className="text-destructive mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Something went wrong</p>
        <p className="text-muted-foreground mt-0.5 text-sm break-words">{errorMessage(error)}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
