import type { MatchType, RulePreview } from "@/screens/rules/queries";
import { transactionCount } from "@/screens/transactions/format";

const MATCH_TYPE_LABELS: Record<MatchType, string> = {
  contains: "Contains the words",
  regex: "Regular expression",
};

/** The match types in the order the form offers them. */
export const MATCH_TYPES = (Object.keys(MATCH_TYPE_LABELS) as MatchType[]).map((value) => ({
  value,
  label: MATCH_TYPE_LABELS[value],
}));

export function matchTypeLabel(matchType: MatchType): string {
  return MATCH_TYPE_LABELS[matchType];
}

/** How a match type works, shown before anything is typed. */
export function matchTypeHint(matchType: MatchType): string {
  return matchType === "regex"
    ? "A regular expression, searched in the merchant name and the bank's description. Case doesn't matter."
    : "Matches whole words in the merchant name or the bank's description. Case, accents and punctuation don't matter.";
}

/** `"Matches 14 transactions, such as Uber, Uber Eats. 1 transaction you categorized ..."` */
export function previewSummary({ matching, user_set: userSet, examples }: RulePreview): string {
  if (matching === 0) return "Matches no transactions yet. It will apply to future imports.";
  const such = examples.length > 0 ? `, such as ${examples.join(", ")}` : "";
  const kept =
    userSet === 0
      ? ""
      : ` ${transactionCount(userSet)} you categorized yourself ${userSet === 1 ? "keeps its" : "keep their"} category.`;
  return `Matches ${transactionCount(matching)}${such}.${kept}`;
}
