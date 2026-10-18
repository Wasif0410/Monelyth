import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { queryKeys } from "@/api/queries";
import { errorMessage } from "@/lib/utils";
import {
  filtersToSearchParams,
  parseFilters,
  toListQuery,
  type ListQuery,
  type TransactionFilters,
} from "@/screens/transactions/filters";

export type Transaction = Schemas["TransactionOut"];
type TransactionPage = Schemas["TransactionPageOut"];
type TransactionPages = InfiniteData<TransactionPage, number>;

/** Rows per request: enough to fill several screens, small enough to arrive instantly. */
export const PAGE_SIZE = 200;

const transactionKeys = {
  lists: [...queryKeys.transactions, "list"] as const,
  list: (query: ListQuery) => [...transactionKeys.lists, query] as const,
  range: [...queryKeys.transactions, "range"] as const,
};

/** The filters in the URL, and a setter that writes them back (dropping unused ones). */
export function useTransactionFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const setFilters = useCallback(
    (next: TransactionFilters, options: { replace?: boolean } = {}) => {
      setSearchParams(filtersToSearchParams(next), { replace: options.replace ?? false });
    },
    [setSearchParams],
  );
  return [filters, setFilters] as const;
}

/** The matching transactions, newest first, fetched a page at a time as the table scrolls. */
export function useTransactionPages(filters: TransactionFilters) {
  const api = useApi();
  const query = toListQuery(filters);
  return useInfiniteQuery({
    queryKey: transactionKeys.list(query),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET("/transactions", {
          params: { query: { ...query, limit: PAGE_SIZE, offset: pageParam } },
          signal,
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0);
      return lastPage.items.length > 0 && loaded < lastPage.total ? loaded : undefined;
    },
    // Keep showing the current rows while a new filter loads, instead of flashing a skeleton.
    placeholderData: keepPreviousData,
  });
}

/** The first and last transaction dates; both `null` while nothing has been imported. */
export function useTransactionRange() {
  const api = useApi();
  return useQuery({
    queryKey: transactionKeys.range,
    queryFn: ({ signal }) => unwrap(api.GET("/transactions/range", { signal })),
  });
}

interface CategoryChange {
  /** The row as shown when the user picked the category, restored if the change fails. */
  transaction: Transaction;
  categoryId: number;
}

/**
 * Set a transaction's category. The table shows the new category at once; if the engine
 * refuses, the row goes back to what it was and a toast says why.
 */
export function useSetCategory() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ transaction, categoryId }: CategoryChange) =>
      unwrap(
        api.PATCH("/transactions/{transaction_id}", {
          params: { path: { transaction_id: transaction.id } },
          body: { category_id: categoryId },
        }),
      ),
    onMutate: async ({ transaction, categoryId }) => {
      // A fetch finishing now would overwrite the optimistic row with the old one.
      await queryClient.cancelQueries({ queryKey: transactionKeys.lists });
      // What the engine does for a category the user chose (see PATCH /transactions/{id}).
      replaceCachedTransaction(queryClient, {
        ...transaction,
        category_id: categoryId,
        category_source: "user",
        confidence: null,
        needs_review: false,
      });
    },
    onError: (error, { transaction }) => {
      replaceCachedTransaction(queryClient, transaction);
      toast.error("Couldn't change the category", { description: errorMessage(error) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.transactions });
    },
    onSuccess: (updated) => {
      replaceCachedTransaction(queryClient, updated);
      // Lists that filter on the category or the review flag may gain or lose this row, and
      // their totals and page offsets shift, so they reload. Every other list already shows
      // the saved row in its place.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.transactions,
        predicate: (query) => !isListIndependentOfCategory(query.queryKey),
      });
    },
  });
}

function replaceCachedTransaction(queryClient: QueryClient, next: Transaction) {
  queryClient.setQueriesData<TransactionPages>({ queryKey: transactionKeys.lists }, (data) =>
    data === undefined
      ? undefined
      : {
          ...data,
          pages: data.pages.map((page) =>
            page.items.some((tx) => tx.id === next.id)
              ? { ...page, items: page.items.map((tx) => (tx.id === next.id ? next : tx)) }
              : page,
          ),
        },
  );
}

function isListIndependentOfCategory(queryKey: QueryKey): boolean {
  const [, kind, query] = queryKey;
  if (kind !== "list" || typeof query !== "object" || query === null) return false;
  return !("category_id" in query || "categorized" in query || "needs_review" in query);
}
