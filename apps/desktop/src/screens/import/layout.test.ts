import { describe, expect, it } from "vitest";

import {
  assignColumn,
  choicesFromDraft,
  missingParts,
  sameChoices,
  setAmountKind,
  toLayout,
  type CsvLayoutDraft,
  type LayoutChoices,
} from "@/screens/import/layout";

const DRAFT: CsvLayoutDraft = {
  version: 1,
  encoding: "utf-8-sig",
  delimiter: ",",
  skip_rows: 0,
  has_header: true,
  date_column: 0,
  description_column: 1,
  amount: { kind: "signed", column: 2 },
  date_format: "%Y-%m-%d",
  decimal_separator: ".",
  invert_signs: false,
};

const CHOICES: LayoutChoices = choicesFromDraft(DRAFT);

describe("choicesFromDraft and toLayout", () => {
  it("round-trip a complete layout exactly", () => {
    expect(toLayout(DRAFT, CHOICES)).toEqual(DRAFT);
  });

  it("round-trip debit and credit columns", () => {
    const draft: CsvLayoutDraft = {
      ...DRAFT,
      amount: { kind: "debit_credit", debit_column: 2, credit_column: 3 },
    };

    expect(toLayout(draft, choicesFromDraft(draft))).toEqual(draft);
  });

  it("give no layout while a part is undecided", () => {
    const choices = choicesFromDraft({ ...DRAFT, amount: null, date_format: null });

    expect(choices.amountKind).toBe("signed");
    expect(toLayout(DRAFT, choices)).toBeNull();
    expect(missingParts(choices)).toEqual(["the date format", "the amount column"]);
  });
});

describe("assignColumn", () => {
  it("swaps two roles when a column is taken", () => {
    const next = assignColumn(CHOICES, "date", 1);

    expect(next.dateColumn).toBe(1);
    expect(next.descriptionColumn).toBe(0);
    expect(next.amountColumn).toBe(2);
  });

  it("leaves the other roles alone for a free column", () => {
    const next = assignColumn(CHOICES, "amount", 4);

    expect(next).toEqual({ ...CHOICES, amountColumn: 4 });
  });

  it("leaves a role empty when the role taking its column had none", () => {
    const next = assignColumn({ ...CHOICES, descriptionColumn: null }, "description", 0);

    expect(next.descriptionColumn).toBe(0);
    expect(next.dateColumn).toBeNull();
  });

  it("ignores columns kept for the amount kind not in use", () => {
    const choices = { ...CHOICES, debitColumn: 3 };

    expect(assignColumn(choices, "amount", 3).debitColumn).toBe(3);
  });
});

describe("setAmountKind", () => {
  it("starts debit and credit from the signed column, and never inverts them", () => {
    const next = setAmountKind({ ...CHOICES, invertSigns: true }, "debit_credit");

    expect(next).toMatchObject({
      amountKind: "debit_credit",
      debitColumn: 2,
      creditColumn: null,
      invertSigns: false,
    });
    expect(missingParts(next)).toEqual(["the money-in column"]);
  });

  it("restores the earlier signed column when switching back", () => {
    const debitCredit = assignColumn(setAmountKind(CHOICES, "debit_credit"), "credit", 3);

    const signed = setAmountKind(debitCredit, "signed");

    expect(signed.amountColumn).toBe(2);
    expect(toLayout(DRAFT, signed)).toEqual(DRAFT);
  });

  it("drops a remembered column that the date or description now uses", () => {
    const choices = { ...CHOICES, amountColumn: null, debitColumn: 1, dateColumn: 0 };

    expect(setAmountKind(choices, "signed")).toBe(choices);
    expect(setAmountKind({ ...choices, amountKind: "debit_credit" }, "signed").amountColumn).toBe(
      null,
    );
  });
});

describe("sameChoices", () => {
  it("compares every choice", () => {
    expect(sameChoices(CHOICES, { ...CHOICES })).toBe(true);
    expect(sameChoices(CHOICES, { ...CHOICES, dateFormat: "%d/%m/%Y" })).toBe(false);
  });
});
