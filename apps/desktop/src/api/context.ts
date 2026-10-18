import { createContext, useContext } from "react";

import type { ApiClient } from "@/api/client";

export const ApiContext = createContext<ApiClient | null>(null);

/** The engine client. Only available inside `ApiProvider`, i.e. once the engine is connected. */
export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (client === null) throw new Error("useApi must be used inside ApiProvider");
  return client;
}
