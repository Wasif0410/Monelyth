import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { createApiClient, type ApiClient } from "@/api/client";
import { ApiContext } from "@/api/context";
import type { EngineConnection } from "@/engine/status";

interface ApiProviderProps {
  connection: EngineConnection;
  children: ReactNode;
}

/** Gives every screen a typed engine client and a shared query cache. */
export function ApiProvider({ connection, children }: ApiProviderProps) {
  // Created once per engine connection; App remounts this provider (via `key`) if the
  // engine restarts on a new port, which also drops any cached data from the old engine.
  const [client] = useState<ApiClient>(() => createApiClient(connection));
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // The engine is local and fast; a failure is a real error, not a flaky network.
            retry: false,
            refetchOnWindowFocus: false,
            staleTime: 30_000,
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <ApiContext.Provider value={client}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ApiContext.Provider>
  );
}
