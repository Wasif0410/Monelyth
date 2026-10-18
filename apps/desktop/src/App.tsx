import { useState } from "react";
import { RouterProvider } from "react-router";
import { Toaster } from "sonner";

import { ApiProvider } from "@/api/ApiProvider";
import { StartupScreen } from "@/components/StartupScreen";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useEngineHealth } from "@/engine/useEngineHealth";
import { useEngineStatus } from "@/engine/useEngineStatus";
import { createAppRouter } from "@/routes";

export function App() {
  const status = useEngineStatus();
  const health = useEngineHealth(status);
  const [router] = useState(createAppRouter);

  if (status.state !== "ready" || health.kind !== "ok") {
    return <StartupScreen status={status} health={health} />;
  }

  const connection = { port: status.port, token: status.token };
  return (
    // Keyed by the connection: if the engine ever restarts on a new port, every query
    // starts fresh against the new engine.
    <ApiProvider key={`${String(connection.port)}:${connection.token}`} connection={connection}>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" theme="system" richColors closeButton />
      </TooltipProvider>
    </ApiProvider>
  );
}
