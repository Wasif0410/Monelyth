/**
 * Queries and mutations shared by several screens. Screen-specific ones live with their screen,
 * but must use `queryKeys` so a change anywhere refreshes every view of the same data.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";

export const queryKeys = {
  accounts: ["accounts"] as const,
  categories: ["categories"] as const,
  /** Prefix of every transaction list query; invalidate it after anything changes them. */
  transactions: ["transactions"] as const,
};

export type Account = Schemas["AccountOut"];
export type AccountCreate = Schemas["AccountCreate"];
export type Category = Schemas["CategoryOut"];

export function useAccounts() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => unwrap(api.GET("/accounts", { signal })),
  });
}

export function useCreateAccount() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AccountCreate) => unwrap(api.POST("/accounts", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
  });
}

export function useCategories() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: ({ signal }) => unwrap(api.GET("/categories", { signal })),
    // Categories change only when the user edits them (a later phase).
    staleTime: Infinity,
  });
}
