import { useMutation, useQueryClient } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { queryKeys } from "@/api/queries";

export type DemoResult = Schemas["DemoOut"];

/**
 * Add the demo accounts and a year of demo transactions in `currency`.
 *
 * The mutation stays pending until the accounts and transactions have been refetched, so the
 * screen it leads to opens with the demo data already loaded.
 */
export function useAddDemoData() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (currency: string) => unwrap(api.POST("/demo", { body: { currency } })),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.transactions }),
      ]),
  });
}
