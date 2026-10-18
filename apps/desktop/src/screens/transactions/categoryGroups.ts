import type { Category } from "@/api/queries";

export interface CategoryGroup {
  label: string;
  categories: Category[];
}

const KIND_LABELS: Record<Category["kind"], string> = {
  expense: "Spending",
  income: "Income",
  transfer: "Transfers",
};

/** Categories grouped by kind (spending first) and sorted by name, for pickers. */
export function groupCategories(categories: readonly Category[]): CategoryGroup[] {
  return (Object.keys(KIND_LABELS) as Category["kind"][])
    .map((kind) => ({
      label: KIND_LABELS[kind],
      categories: categories
        .filter((category) => category.kind === kind)
        .sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .filter((group) => group.categories.length > 0);
}
