import { useEffect, useId, useState, type SubmitEvent } from "react";
import { toast } from "sonner";

import { useCategories } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { errorMessage } from "@/lib/utils";
import { MATCH_TYPES, matchTypeHint, previewSummary } from "@/screens/rules/text";
import {
  MAX_PATTERN_LENGTH,
  MAX_PRIORITY,
  useCreateRule,
  useRulePreview,
  useUpdateRule,
  type MatchType,
  type Rule,
} from "@/screens/rules/queries";
import { groupCategories } from "@/screens/transactions/categoryGroups";

/** How long typing must pause before the pattern is checked against the transactions. */
export const PREVIEW_DEBOUNCE_MS = 300;

interface RuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The rule to edit, or `null` to add a new one. */
  rule: Rule | null;
}

export function RuleDialog({ open, onOpenChange, rule }: RuleDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{rule ? "Edit rule" : "Add rule"}</DialogTitle>
          <DialogDescription>
            Anything that matches gets the category you choose, here and in future imports.
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so every opening starts from the rule as saved. */}
        <RuleForm
          rule={rule}
          onDone={() => {
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

function RuleForm({ rule, onDone }: { rule: Rule | null; onDone: () => void }) {
  const categories = useCategories();
  const createRule = useCreateRule();
  const updateRule = useUpdateRule();
  const saving = rule ? updateRule : createRule;
  const [pattern, setPattern] = useState(rule?.pattern ?? "");
  const [matchType, setMatchType] = useState<MatchType>(rule?.match_type ?? "contains");
  const [categoryId, setCategoryId] = useState(rule ? String(rule.category_id) : "");
  const [priority, setPriority] = useState(String(rule?.priority ?? 0));
  const preview = useRulePreview(useDebounced(pattern, PREVIEW_DEBOUNCE_MS), matchType);
  const ids = {
    pattern: useId(),
    matchType: useId(),
    category: useId(),
    priority: useId(),
    priorityHint: useId(),
    preview: useId(),
    error: useId(),
  };

  const priorityValue = Number(priority);
  const priorityValid =
    priority.trim() !== "" &&
    Number.isInteger(priorityValue) &&
    priorityValue >= 0 &&
    priorityValue <= MAX_PRIORITY;
  const canSave = pattern.trim() !== "" && categoryId !== "" && priorityValid && !saving.isPending;

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) return;
    const body = {
      pattern,
      match_type: matchType,
      category_id: Number(categoryId),
      priority: priorityValue,
    };
    const onSuccess = () => {
      toast.success(rule ? "Rule saved" : "Rule added", {
        description: "Matching transactions are being categorized again.",
      });
      onDone();
    };
    if (rule) updateRule.mutate({ id: rule.id, ...body }, { onSuccess });
    else createRule.mutate(body, { onSuccess });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4"
      aria-describedby={saving.isError ? ids.error : undefined}
    >
      <div className="grid grid-cols-[1fr_auto] gap-3">
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.pattern}>Look for</Label>
          <Input
            id={ids.pattern}
            value={pattern}
            onChange={(event) => {
              setPattern(event.target.value);
            }}
            placeholder={matchType === "regex" ? "e.g. ^uber\\s*eats" : "e.g. blue bottle"}
            maxLength={MAX_PATTERN_LENGTH}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={ids.preview}
            required
            autoFocus
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.matchType}>Match</Label>
          <Select
            value={matchType}
            onValueChange={(value) => {
              const found = MATCH_TYPES.find((type) => type.value === value);
              if (found) setMatchType(found.value);
            }}
          >
            <SelectTrigger id={ids.matchType} className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              {MATCH_TYPES.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <PreviewLine id={ids.preview} pattern={pattern} matchType={matchType} preview={preview} />

      <div className="grid grid-cols-[1fr_auto] gap-3">
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.category}>Category</Label>
          <Select value={categoryId} onValueChange={setCategoryId}>
            <SelectTrigger id={ids.category} className="w-full">
              <SelectValue placeholder="Choose a category" />
            </SelectTrigger>
            <SelectContent position="popper" className="max-h-72">
              {groupCategories(categories.data ?? []).map((group) => (
                <SelectGroup key={group.label}>
                  <SelectLabel>{group.label}</SelectLabel>
                  {group.categories.map((category) => (
                    <SelectItem key={category.id} value={String(category.id)}>
                      {category.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={ids.priority}>Priority</Label>
          <Input
            id={ids.priority}
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_PRIORITY}
            step={1}
            value={priority}
            onChange={(event) => {
              setPriority(event.target.value);
            }}
            aria-invalid={!priorityValid}
            aria-describedby={ids.priorityHint}
            className="w-24"
          />
        </div>
      </div>
      <p id={ids.priorityHint} className="text-muted-foreground -mt-2 text-xs">
        When several of your rules match, the highest priority wins. Your rules always come before
        the built-in ones.
      </p>

      {saving.isError ? (
        <p id={ids.error} role="alert" className="text-destructive text-sm">
          {errorMessage(saving.error)}
        </p>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={saving.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canSave}>
          {saving.isPending ? "Saving…" : rule ? "Save rule" : "Add rule"}
        </Button>
      </DialogFooter>
    </form>
  );
}

interface PreviewLineProps {
  id: string;
  pattern: string;
  matchType: MatchType;
  preview: ReturnType<typeof useRulePreview>;
}

/** What the pattern matches right now, or why it can't be used. */
function PreviewLine({ id, pattern, matchType, preview }: PreviewLineProps) {
  let text: string;
  let tone = "text-muted-foreground";
  if (pattern.trim() === "") {
    text = matchTypeHint(matchType);
  } else if (preview.isError) {
    text = errorMessage(preview.error);
    tone = "text-destructive";
  } else if (preview.data === undefined) {
    text = "Checking your transactions…";
  } else {
    text = previewSummary(preview.data);
  }
  return (
    <p id={id} aria-live="polite" className={`-mt-1 text-sm ${tone}`}>
      {text}
    </p>
  );
}

/** `value`, once it has stopped changing for `delayMs`. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delayMs]);
  return debounced;
}
