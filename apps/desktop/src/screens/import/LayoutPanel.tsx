import { CircleCheck, CircleHelp } from "lucide-react";
import { useId, useState } from "react";

import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  assignColumn,
  columnFor,
  setAmountKind,
  type AmountKind,
  type ColumnRole,
  type LayoutChoices,
} from "@/screens/import/layout";

interface LayoutPanelProps {
  /** The engine's first reading of the file: its columns, questions and date formats. */
  csv: Schemas["CsvPreviewOut"];
  choices: LayoutChoices;
  onChange: (choices: LayoutChoices) => void;
  disabled: boolean;
}

const AMOUNT_KINDS: readonly Option[] = [
  { value: "signed", label: "In one column" },
  { value: "debit_credit", label: "In money-out and money-in columns" },
];

const SIGN_OPTIONS: readonly Option[] = [
  { value: "negative", label: "Negative numbers" },
  { value: "positive", label: "Positive numbers" },
];

/** Controls for how a CSV statement is laid out, with the engine's questions about it. */
export function LayoutPanel({ csv, choices, onChange, disabled }: LayoutPanelProps) {
  const saved = csv.layout_source === "saved";
  // A layout confirmed before needs no attention; a new one should be checked once.
  const [expanded, setExpanded] = useState(!saved);
  const controlsId = useId();

  const columnOptions = csv.columns.map((name, index) => ({
    value: String(index),
    label: name.trim() || `Column ${String(index + 1)}`,
  }));
  const dateFormatOptions = csv.date_formats.map((format) => ({
    value: format.code,
    label: format.label,
  }));

  function columnField(role: ColumnRole, label: string) {
    const column = columnFor(choices, role);
    return (
      <ChoiceField
        label={label}
        value={column === null ? "" : String(column)}
        options={columnOptions}
        disabled={disabled}
        onChange={(value) => {
          onChange(assignColumn(choices, role, Number(value)));
        }}
      />
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h2 className="text-base font-semibold">Columns</h2>
            {saved ? (
              <p className="text-muted-foreground mt-1 flex items-center gap-1.5 text-sm">
                <CircleCheck aria-hidden="true" className="text-success size-4 shrink-0" />
                Using the layout you confirmed for this bank.
              </p>
            ) : (
              <p className="text-muted-foreground mt-1 text-sm">
                Check how Monelyth reads this file. Your choices are remembered for this bank.
              </p>
            )}
          </div>
          {saved ? (
            <Button
              variant="outline"
              size="sm"
              aria-expanded={expanded}
              aria-controls={controlsId}
              onClick={() => {
                setExpanded(!expanded);
              }}
            >
              {expanded ? "Hide columns" : "Change columns"}
            </Button>
          ) : null}
        </div>

        {csv.questions.length > 0 ? (
          <ul aria-label="Questions about this file" className="flex flex-col gap-2">
            {csv.questions.map((question, index) => (
              <li
                key={`${question.kind}-${String(index)}`}
                className="bg-warning/10 flex items-start gap-2.5 rounded-md px-3 py-2.5 text-sm"
              >
                <CircleHelp aria-hidden="true" className="text-warning mt-0.5 size-4 shrink-0" />
                <span>{question.message}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {expanded ? (
          <div id={controlsId} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {columnField("date", "Date column")}
            <ChoiceField
              label="Date format"
              value={choices.dateFormat ?? ""}
              options={dateFormatOptions}
              disabled={disabled}
              onChange={(value) => {
                onChange({ ...choices, dateFormat: value });
              }}
            />
            {columnField("description", "Description column")}
            <ChoiceField
              label="Amounts"
              value={choices.amountKind}
              options={AMOUNT_KINDS}
              disabled={disabled}
              onChange={(value) => {
                onChange(setAmountKind(choices, value as AmountKind));
              }}
            />
            {choices.amountKind === "signed" ? (
              <>
                {columnField("amount", "Amount column")}
                <ChoiceField
                  label="Purchases are shown as"
                  value={signOption(choices.invertSigns)}
                  options={SIGN_OPTIONS}
                  disabled={disabled}
                  onChange={(value) => {
                    onChange({ ...choices, invertSigns: value === "positive" });
                  }}
                />
              </>
            ) : (
              <>
                {columnField("debit", "Money-out column")}
                {columnField("credit", "Money-in column")}
              </>
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function signOption(invertSigns: boolean | null): string {
  if (invertSigns === null) return "";
  return invertSigns ? "positive" : "negative";
}

interface Option {
  value: string;
  label: string;
}

interface ChoiceFieldProps {
  label: string;
  /** An empty string shows the placeholder: nothing chosen yet. */
  value: string;
  options: readonly Option[];
  disabled: boolean;
  onChange: (value: string) => void;
}

function ChoiceField({ label, value, options, disabled, onChange }: ChoiceFieldProps) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger id={id} className="w-full" aria-invalid={value === ""}>
          <SelectValue placeholder="Choose…" />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
