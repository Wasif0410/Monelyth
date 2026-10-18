/**
 * Learning from a correction (PLAN.md 3.8): after the user sets a category, offer to give it to
 * the other transactions from the same merchant ("Apply Coffee to 14 more from Blue Bottle?").
 * The engine has already remembered the choice for new transactions; this covers the past ones.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { toast } from "sonner";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { queryKeys, type Category } from "@/api/queries";
import { errorMessage } from "@/lib/utils";

type Transaction = Schemas["TransactionOut"];

/** Long enough to read the question and reach the button. */
export const PROMPT_DURATION_MS = 12_000;

const countFormat = new Intl.NumberFormat();

/** The question for `count` other transactions from `merchant`. */
export function sameMerchantQuestion(category: string, count: number, merchant: string): string {
  return `Apply ${category} to ${countFormat.format(count)} more from ${merchant}?`;
}

/**
 * Returns a function to call with a transaction the user just categorized. It asks the engine
 * how many others from the merchant would change and, if any, shows the question as a toast
 * whose button applies it. Checking is a convenience: if it fails, nothing is shown.
 */
export function useOfferSameMerchant() {
  const api = useApi();
  const queryClient = useQueryClient();
  const { mutate: apply } = useMutation({
    mutationFn: (transactionId: number) =>
      unwrap(
        api.POST("/transactions/{transaction_id}/same-merchant/apply", {
          params: { path: { transaction_id: transactionId } },
        }),
      ),
    onSuccess: ({ updated }) => {
      toast.success(
        updated === 1
          ? "Updated 1 more transaction"
          : `Updated ${countFormat.format(updated)} more transactions`,
      );
    },
    onError: (error) => {
      toast.error("Couldn't apply the category", { description: errorMessage(error) });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.transactions }),
  });

  return useCallback(
    async (transaction: Transaction) => {
      const category = queryClient
        .getQueryData<Category[]>(queryKeys.categories)
        ?.find((item) => item.id === transaction.category_id);
      if (category === undefined) return;
      let found: Schemas["SameMerchantOut"];
      try {
        found = await unwrap(
          api.GET("/transactions/{transaction_id}/same-merchant", {
            params: { path: { transaction_id: transaction.id } },
          }),
        );
      } catch {
        return;
      }
      if (found.count === 0 || found.merchant === null) return;
      toast(sameMerchantQuestion(category.name, found.count, found.merchant), {
        id: `same-merchant-${String(transaction.id)}`,
        description: "Transactions whose category you set yourself stay as they are.",
        duration: PROMPT_DURATION_MS,
        action: {
          label: "Apply",
          onClick: () => {
            apply(transaction.id);
          },
        },
      });
    },
    [api, queryClient, apply],
  );
}
