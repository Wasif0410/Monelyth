import { describe, expect, it } from "vitest";

import { checkStatementFiles } from "@/screens/import/files";
import { formatAmount, importHeadline, joinAnd, plural } from "@/screens/import/display";

describe("importHeadline", () => {
  it.each([
    [84, 12, "Added 84 transactions, skipped 12 duplicates"],
    [84, 0, "Added 84 transactions"],
    [1, 1, "Added 1 transaction, skipped 1 duplicate"],
    [0, 12, "No new transactions: skipped 12 duplicates"],
  ])("added %i, skipped %i", (added, skipped, expected) => {
    expect(importHeadline(added, skipped)).toBe(expected);
  });
});

describe("wording helpers", () => {
  it("pluralizes", () => {
    expect(plural(1, "row")).toBe("1 row");
    expect(plural(2, "row")).toBe("2 rows");
  });

  it("joins lists", () => {
    expect(joinAnd([])).toBe("");
    expect(joinAnd(["a"])).toBe("a");
    expect(joinAnd(["a", "b"])).toBe("a and b");
    expect(joinAnd(["a", "b", "c"])).toBe("a, b and c");
  });
});

describe("formatAmount", () => {
  it("formats cents exactly without a currency", () => {
    expect(formatAmount(-123456, null)).toBe(
      (-1234.56).toLocaleString(undefined, { minimumFractionDigits: 2 }),
    );
    expect(formatAmount(5, null)).toBe(
      (0.05).toLocaleString(undefined, { minimumFractionDigits: 2 }),
    );
  });
});

describe("checkStatementFiles", () => {
  const csv = new File(["Date,Amount\n"], "statement.csv");

  it("accepts one statement file, whatever the case of its extension", () => {
    expect(checkStatementFiles([csv])).toEqual({ ok: true, file: csv });
    const qfx = new File(["OFXHEADER:100"], "EXPORT.QFX");
    expect(checkStatementFiles([qfx])).toEqual({ ok: true, file: qfx });
  });

  it("rejects several files", () => {
    expect(checkStatementFiles([csv, csv])).toEqual({
      ok: false,
      message: "That's 2 files. Import one statement at a time.",
    });
  });

  it("rejects other kinds of file and empty files", () => {
    expect(checkStatementFiles([new File(["%PDF"], "statement.pdf")]).ok).toBe(false);
    expect(checkStatementFiles([new File([], "empty.csv")]).ok).toBe(false);
    expect(checkStatementFiles([]).ok).toBe(false);
  });
});
