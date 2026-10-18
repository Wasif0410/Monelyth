import { describe, expect, it } from "vitest";

import { matchTypeHint, matchTypeLabel, previewSummary } from "@/screens/rules/text";

describe("previewSummary", () => {
  it("says how many transactions match, with examples", () => {
    expect(previewSummary({ matching: 14, user_set: 0, examples: ["Uber", "Uber Eats"] })).toBe(
      "Matches 14 transactions, such as Uber, Uber Eats.",
    );
  });

  it("says which of them keep the category the user set", () => {
    expect(previewSummary({ matching: 3, user_set: 1, examples: ["Lyft"] })).toBe(
      "Matches 3 transactions, such as Lyft. 1 transaction you categorized yourself keeps its category.",
    );
    expect(previewSummary({ matching: 2, user_set: 2, examples: [] })).toBe(
      "Matches 2 transactions. 2 transactions you categorized yourself keep their category.",
    );
  });

  it("explains a pattern that matches nothing yet", () => {
    expect(previewSummary({ matching: 0, user_set: 0, examples: [] })).toBe(
      "Matches no transactions yet. It will apply to future imports.",
    );
  });
});

describe("match types", () => {
  it("are named and explained for people", () => {
    expect(matchTypeLabel("contains")).toBe("Contains the words");
    expect(matchTypeLabel("regex")).toBe("Regular expression");
    expect(matchTypeHint("contains")).toMatch(/whole words/);
    expect(matchTypeHint("regex")).toMatch(/regular expression/);
  });
});
