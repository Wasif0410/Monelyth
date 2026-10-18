/**
 * The CSV layout controls, as plain data. The engine returns a layout with `null` for each part
 * it couldn't decide; the user fills those in, and `toLayout` turns the answers back into the
 * exact JSON `POST /imports` (and `POST /imports/preview`) accept.
 */
import type { Schemas } from "@/api/client";

/** A layout as the engine describes it, with `null` for undecided parts. */
export type CsvLayoutDraft = Schemas["CsvLayoutOut"];
type AmountColumns = NonNullable<CsvLayoutDraft["amount"]>;

/** A complete layout, ready to send with a preview or an import. */
export type CsvLayout = Omit<
  CsvLayoutDraft,
  "date_column" | "description_column" | "amount" | "date_format" | "invert_signs"
> & {
  date_column: number;
  description_column: number;
  amount: AmountColumns;
  date_format: string;
  invert_signs: boolean;
};

export type AmountKind = AmountColumns["kind"];

/** What the user chooses. Every amount column is kept, so switching kinds back and forth
 * restores the earlier choice. */
export interface LayoutChoices {
  dateColumn: number | null;
  descriptionColumn: number | null;
  amountKind: AmountKind;
  amountColumn: number | null;
  debitColumn: number | null;
  creditColumn: number | null;
  dateFormat: string | null;
  invertSigns: boolean | null;
}

/** A job a column can have. Each column has at most one. */
export type ColumnRole = "date" | "description" | "amount" | "debit" | "credit";

const ROLE_FIELDS = {
  date: "dateColumn",
  description: "descriptionColumn",
  amount: "amountColumn",
  debit: "debitColumn",
  credit: "creditColumn",
} as const satisfies Record<ColumnRole, keyof LayoutChoices>;

export function choicesFromDraft(draft: CsvLayoutDraft): LayoutChoices {
  const { amount } = draft;
  return {
    dateColumn: draft.date_column,
    descriptionColumn: draft.description_column,
    amountKind: amount?.kind ?? "signed",
    amountColumn: amount?.kind === "signed" ? amount.column : null,
    debitColumn: amount?.kind === "debit_credit" ? amount.debit_column : null,
    creditColumn: amount?.kind === "debit_credit" ? amount.credit_column : null,
    dateFormat: draft.date_format,
    invertSigns: draft.invert_signs,
  };
}

/** The roles the layout uses, given how amounts are laid out. */
export function activeRoles(kind: AmountKind): readonly ColumnRole[] {
  return kind === "signed"
    ? ["date", "description", "amount"]
    : ["date", "description", "debit", "credit"];
}

export function columnFor(choices: LayoutChoices, role: ColumnRole): number | null {
  return choices[ROLE_FIELDS[role]];
}

/**
 * Give `column` the job `role`. A column can only have one job, so if another role held it,
 * that role takes this role's previous column: choosing the date column for the description
 * swaps the two, which is almost always what the user meant.
 */
export function assignColumn(
  choices: LayoutChoices,
  role: ColumnRole,
  column: number,
): LayoutChoices {
  const previous = columnFor(choices, role);
  const next: LayoutChoices = { ...choices, [ROLE_FIELDS[role]]: column };
  for (const other of activeRoles(choices.amountKind)) {
    if (other !== role && columnFor(choices, other) === column) {
      next[ROLE_FIELDS[other]] = previous;
    }
  }
  return next;
}

/**
 * Switch between one signed amount column and separate debit and credit columns, starting the
 * new kind from the old kind's column where that makes sense.
 */
export function setAmountKind(choices: LayoutChoices, kind: AmountKind): LayoutChoices {
  if (kind === choices.amountKind) return choices;
  const taken = new Set([choices.dateColumn, choices.descriptionColumn]);
  const free = (column: number | null) => (column !== null && taken.has(column) ? null : column);

  if (kind === "debit_credit") {
    const debitColumn = free(choices.debitColumn ?? choices.amountColumn);
    const creditColumn = free(choices.creditColumn);
    return {
      ...choices,
      amountKind: kind,
      debitColumn,
      creditColumn: creditColumn === debitColumn ? null : creditColumn,
      // A debit always takes money out and a credit always puts it in, whatever their sign.
      invertSigns: false,
    };
  }
  return {
    ...choices,
    amountKind: kind,
    amountColumn: free(choices.amountColumn ?? choices.debitColumn),
  };
}

/** The parts still to choose, in the order the controls show them, as a phrase for each. */
export function missingParts(choices: LayoutChoices): string[] {
  const missing: string[] = [];
  if (choices.dateColumn === null) missing.push("the date column");
  if (choices.dateFormat === null) missing.push("the date format");
  if (choices.descriptionColumn === null) missing.push("the description column");
  if (choices.amountKind === "signed") {
    if (choices.amountColumn === null) missing.push("the amount column");
    if (choices.invertSigns === null) missing.push("how purchases are shown");
  } else {
    if (choices.debitColumn === null) missing.push("the money-out column");
    if (choices.creditColumn === null) missing.push("the money-in column");
  }
  return missing;
}

/** The finished layout, or `null` while any part is still undecided. */
export function toLayout(draft: CsvLayoutDraft, choices: LayoutChoices): CsvLayout | null {
  const { dateColumn, descriptionColumn, dateFormat, invertSigns } = choices;
  const amount = amountColumns(choices);
  if (
    dateColumn === null ||
    descriptionColumn === null ||
    amount === null ||
    dateFormat === null ||
    invertSigns === null
  ) {
    return null;
  }
  return {
    ...draft,
    date_column: dateColumn,
    description_column: descriptionColumn,
    amount,
    date_format: dateFormat,
    invert_signs: invertSigns,
  };
}

export function sameChoices(a: LayoutChoices, b: LayoutChoices): boolean {
  return (Object.keys(a) as (keyof LayoutChoices)[]).every((key) => a[key] === b[key]);
}

function amountColumns(choices: LayoutChoices): AmountColumns | null {
  if (choices.amountKind === "signed") {
    return choices.amountColumn === null ? null : { kind: "signed", column: choices.amountColumn };
  }
  if (choices.debitColumn === null || choices.creditColumn === null) return null;
  return {
    kind: "debit_credit",
    debit_column: choices.debitColumn,
    credit_column: choices.creditColumn,
  };
}
