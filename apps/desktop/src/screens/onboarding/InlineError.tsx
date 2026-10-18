import { CircleAlert } from "lucide-react";

import { errorMessage } from "@/lib/utils";

/** A failed action's message, shown right where the user acted. */
export function InlineError({ error, id }: { error: unknown; id?: string }) {
  return (
    <p
      id={id}
      role="alert"
      className="border-destructive/30 bg-destructive/5 flex items-start gap-2 rounded-md border px-3 py-2.5 text-sm"
    >
      <CircleAlert aria-hidden="true" className="text-destructive mt-0.5 size-4 shrink-0" />
      <span className="min-w-0 break-words">{errorMessage(error)}</span>
    </p>
  );
}
