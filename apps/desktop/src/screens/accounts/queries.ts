/** Mutations only the Accounts screen uses. Listing and adding accounts are shared (`@/api/queries`). */
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { queryKeys, type Account } from "@/api/queries";

export type AccountUpdate = Schemas["AccountUpdate"];
export type AccountDeletion = Schemas["AccountDeletionOut"];

/** Rename an account or change its institution. */
export function useUpdateAccount() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: AccountUpdate & { id: number }) =>
      unwrap(api.PATCH("/accounts/{account_id}", { params: { path: { account_id: id } }, body })),
    onSuccess: (updated) => {
      // Show the new name at once instead of after the refetch.
      queryClient.setQueryData<Account[]>(queryKeys.accounts, (accounts) =>
        accounts?.map((account) => (account.id === updated.id ? updated : account)),
      );
      return refreshAccountData(queryClient);
    },
  });
}

/** Delete an account with all of its imports and transactions. */
export function useDeleteAccount() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE("/accounts/{account_id}", { params: { path: { account_id: id } } })),
    onSuccess: () => refreshAccountData(queryClient),
  });
}

function refreshAccountData(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
    // Transaction lists show account names, and a deleted account's rows are gone.
    queryClient.invalidateQueries({ queryKey: queryKeys.transactions }),
  ]);
}
