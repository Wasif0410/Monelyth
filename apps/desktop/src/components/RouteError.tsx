import { TriangleAlert } from "lucide-react";
import { isRouteErrorResponse, useRouteError } from "react-router";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/utils";

/** Shown instead of a screen that crashed while rendering, so the app never goes blank. */
export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${String(error.status)} ${error.statusText}`
    : errorMessage(error);

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div role="alert" className="flex max-w-md flex-col items-center gap-4 text-center">
        <TriangleAlert aria-hidden="true" className="text-warning size-10" />
        <div>
          <h1 className="text-xl font-semibold">This screen ran into a problem</h1>
          <p className="text-muted-foreground mt-2 text-sm break-words">{message}</p>
        </div>
        <Button
          onClick={() => {
            window.location.hash = "#/";
            window.location.reload();
          }}
        >
          Go back to the start
        </Button>
      </div>
    </main>
  );
}
