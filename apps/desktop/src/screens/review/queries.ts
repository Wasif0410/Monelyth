/**
 * The review queue and background categorization. Their query keys sit under
 * `queryKeys.transactions`: both are views of the transactions, so anything that changes
 * transactions (an import, demo data, deleting an account, a category change) refreshes them.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { queryKeys } from "@/api/queries";

export type Transaction = Schemas["TransactionOut"];
export type CategorizationStatus = Schemas["CategorizationStatusOut"];
export type CategorySource = NonNullable<Transaction["category_source"]>;

export const reviewKeys = {
  summary: [...queryKeys.transactions, "review-summary"] as const,
  queue: [...queryKeys.transactions, "review-queue"] as const,
  categorization: [...queryKeys.transactions, "categorization-status"] as const,
};

/** How many waiting transactions the review screen loads at a time. */
export const REVIEW_PAGE_SIZE = 100;
/** How often to check on a background run while one is going. */
export const STATUS_POLL_MS = 1000;

/** How many transactions wait for review, and how many of them have a suggestion. */
export function useReviewSummary() {
  const api = useApi();
  return useQuery({
    queryKey: reviewKeys.summary,
    queryFn: ({ signal }) => unwrap(api.GET("/review/summary", { signal })),
  });
}

/** The first transactions waiting for review, newest first. */
export function useReviewQueue() {
  const api = useApi();
  return useQuery({
    queryKey: reviewKeys.queue,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/transactions", {
          params: { query: { needs_review: true, limit: REVIEW_PAGE_SIZE } },
          signal,
        }),
      ),
  });
}

/** Accept the suggested category of these transactions. */
export function useAcceptSuggestions() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (transactionIds: readonly number[]) =>
      unwrap(api.POST("/review/accept", { body: { transaction_ids: [...transactionIds] } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.transactions }),
  });
}

/** Accept every suggestion waiting for review. */
export function useAcceptAllSuggestions() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/review/accept-all", { body: {} })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.transactions }),
  });
}

/**
 * The background categorization run, checked every second while one is going. When a run
 * ends, every transaction view refreshes, since categories (and the review queue) may have
 * changed. Mount once, in the app layout, so that happens on every screen.
 */
export function useCategorizationStatus() {
  const api = useApi();
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: reviewKeys.categorization,
    queryFn: ({ signal }) => unwrap(api.GET("/categorization/status", { signal })),
    refetchInterval: (query) =>
      query.state.data !== undefined && query.state.data.state !== "idle" ? STATUS_POLL_MS : false,
  });

  const runsFinished = status.data?.runs_finished;
  const seenRuns = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (runsFinished === undefined) return;
    if (seenRuns.current !== undefined && runsFinished !== seenRuns.current) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.transactions,
        predicate: (query) => !isCategorizationKey(query.queryKey),
      });
    }
    seenRuns.current = runsFinished;
  }, [runsFinished, queryClient]);

  return status;
}

/** Refresh the categorization status, e.g. after something that queues a run. */
export function refreshCategorizationStatus(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: reviewKeys.categorization });
}

function isCategorizationKey(queryKey: QueryKey): boolean {
  return queryKey[1] === reviewKeys.categorization[1];
}
