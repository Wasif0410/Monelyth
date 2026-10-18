/**
 * Categorization rules. Every change re-categorizes matching transactions in the background,
 * so after one the categorization status refreshes (and, when the run ends, the transactions;
 * see `useCategorizationStatus`).
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { ApiError, unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { refreshCategorizationStatus } from "@/screens/review/queries";

export type Rule = Schemas["RuleOut"];
export type RuleCreate = Schemas["RuleCreate"];
export type MatchType = Rule["match_type"];
export type RulePreview = Schemas["RulePreviewOut"];

export const ruleKeys = {
  all: ["rules"] as const,
  list: ["rules", "list"] as const,
  preview: (pattern: string, matchType: MatchType) =>
    ["rules", "preview", { pattern, matchType }] as const,
};

/** Must match the engine's limits (`api/rules.py`, `categorize/rules.py`). */
export const MAX_PATTERN_LENGTH = 200;
export const MAX_PRIORITY = 1000;

export function useRules() {
  const api = useApi();
  return useQuery({
    queryKey: ruleKeys.list,
    queryFn: ({ signal }) => unwrap(api.GET("/rules", { signal })),
  });
}

/**
 * What a pattern matches among the stored transactions. Disabled for a blank pattern. An
 * unusable pattern comes back as an error whose message says why.
 */
export function useRulePreview(pattern: string, matchType: MatchType) {
  const api = useApi();
  return useQuery({
    queryKey: ruleKeys.preview(pattern, matchType),
    queryFn: ({ signal }) =>
      unwrap(api.POST("/rules/preview", { body: { pattern, match_type: matchType }, signal })),
    enabled: pattern.trim() !== "",
    // Keep showing the last count while the next one loads, instead of flickering.
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useCreateRule() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RuleCreate) => unwrap(api.POST("/rules", { body })),
    onSuccess: () => refreshAfterRuleChange(queryClient),
  });
}

export function useUpdateRule() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: RuleCreate & { id: number }) =>
      unwrap(api.PATCH("/rules/{rule_id}", { params: { path: { rule_id: id } }, body })),
    onSuccess: () => refreshAfterRuleChange(queryClient),
  });
}

export function useDeleteRule() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { response, error } = await api.DELETE("/rules/{rule_id}", {
        params: { path: { rule_id: id } },
      });
      // 204 has no body, so `unwrap` (which expects one) doesn't fit.
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => refreshAfterRuleChange(queryClient),
  });
}

function refreshAfterRuleChange(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ruleKeys.all }),
    refreshCategorizationStatus(queryClient),
  ]);
}
