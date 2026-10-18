import type { CategorySource } from "@/screens/review/queries";

const SOURCE_NAMES: Record<CategorySource, string> = {
  memory: "merchant memory",
  rule: "a rule",
  classifier: "the classifier",
  llm: "the local AI model",
  user: "you",
};

const percentFormat = new Intl.NumberFormat(undefined, { style: "percent" });

/** Where a suggestion came from and how sure it is, e.g. "From the classifier, 62% sure". */
export function suggestionOrigin(source: CategorySource, confidence: number | null): string {
  const origin = `From ${SOURCE_NAMES[source]}`;
  return confidence === null ? origin : `${origin}, ${percentFormat.format(confidence)} sure`;
}

const countFormat = new Intl.NumberFormat();

/** `3` → `"3 suggestions"`. */
export function suggestionCount(count: number): string {
  return `${countFormat.format(count)} ${count === 1 ? "suggestion" : "suggestions"}`;
}
