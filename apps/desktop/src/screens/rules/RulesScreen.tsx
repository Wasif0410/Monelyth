import { Info, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { useCategories } from "@/api/queries";
import { QueryError } from "@/components/QueryError";
import { ScreenHeader } from "@/components/ScreenHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteRuleDialog } from "@/screens/rules/DeleteRuleDialog";
import { useRules, type Rule } from "@/screens/rules/queries";
import { RuleDialog } from "@/screens/rules/RuleDialog";
import { matchTypeLabel } from "@/screens/rules/text";

/**
 * The rules that categorize transactions automatically: the user's own, which they can add,
 * edit and delete, and the built-in ones, read-only.
 */
export function RulesScreen() {
  const rules = useRules();
  const categories = useCategories();
  const [editing, setEditing] = useState<{ rule: Rule | null } | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const [search, setSearch] = useState("");

  const categoryNames = useMemo(
    () => new Map((categories.data ?? []).map((category) => [category.id, category.name])),
    [categories.data],
  );
  const mine = rules.data?.filter((rule) => rule.created_by === "user") ?? [];
  const builtIn = rules.data?.filter((rule) => rule.created_by === "system") ?? [];
  const needle = search.trim().toLocaleLowerCase();
  const shownBuiltIn =
    needle === ""
      ? builtIn
      : builtIn.filter(
          (rule) =>
            rule.pattern.toLocaleLowerCase().includes(needle) ||
            (categoryNames.get(rule.category_id) ?? "").toLocaleLowerCase().includes(needle),
        );

  let content: ReactNode;
  const failed = [rules, categories].find((query) => query.isError);
  if (failed) {
    content = (
      <QueryError
        error={failed.error}
        onRetry={() => {
          if (rules.isError) void rules.refetch();
          if (categories.isError) void categories.refetch();
        }}
      />
    );
  } else if (!rules.data || !categories.data) {
    content = <RulesSkeleton />;
  } else {
    content = (
      <>
        <section aria-labelledby="your-rules" className="flex flex-col gap-3">
          <h2 id="your-rules" className="font-medium">
            Your rules
          </h2>
          {mine.length === 0 ? (
            <Card className="text-muted-foreground px-5 py-6 text-sm">
              You haven't made any rules yet. Add one to always put a merchant, or anything with
              certain words, in the same category.
            </Card>
          ) : (
            <RulesTable
              label="Your rules"
              rules={mine}
              categoryNames={categoryNames}
              onEdit={(rule) => {
                setEditing({ rule });
              }}
              onDelete={setDeleting}
            />
          )}
        </section>

        <section aria-labelledby="built-in-rules" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="built-in-rules" className="font-medium">
                Built-in rules
              </h2>
              <p className="text-muted-foreground mt-0.5 text-sm">
                {builtIn.length} rules for well-known merchants. To change one, add your own rule
                for the same words.
              </p>
            </div>
            <div className="relative w-64">
              <Search
                aria-hidden="true"
                className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
              />
              <Input
                type="search"
                aria-label="Search built-in rules"
                placeholder="Search words or categories"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                }}
                className="pl-9"
              />
            </div>
          </div>
          {shownBuiltIn.length === 0 ? (
            <Card className="text-muted-foreground px-5 py-6 text-sm">
              No built-in rule matches “{search.trim()}”.
            </Card>
          ) : (
            <RulesTable label="Built-in rules" rules={shownBuiltIn} categoryNames={categoryNames} />
          )}
        </section>
      </>
    );
  }

  return (
    <>
      <ScreenHeader
        title="Rules"
        description="How Monelyth picks a category when it hasn't learned the merchant from you."
        actions={
          <Button
            onClick={() => {
              setEditing({ rule: null });
            }}
            disabled={!rules.data || !categories.data}
          >
            <Plus aria-hidden="true" />
            Add rule
          </Button>
        }
      />
      <div className="flex max-w-4xl flex-col gap-8">
        <p className="bg-accent/60 flex items-start gap-3 rounded-lg px-4 py-3 text-sm">
          <Info aria-hidden="true" className="text-primary mt-0.5 size-4 shrink-0" />
          <span>
            Adding, editing or deleting a rule categorizes the transactions it matches again, in the
            background.{" "}
            <strong className="font-medium">Categories you set yourself never change.</strong>
          </span>
        </p>
        {content}
      </div>
      <RuleDialog
        open={editing !== null}
        rule={editing?.rule ?? null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      />
      <DeleteRuleDialog
        rule={deleting}
        onClose={() => {
          setDeleting(null);
        }}
      />
    </>
  );
}

interface RulesTableProps {
  label: string;
  rules: readonly Rule[];
  categoryNames: ReadonlyMap<number, string>;
  /** With these, each row gets Edit and Delete buttons. */
  onEdit?: (rule: Rule) => void;
  onDelete?: (rule: Rule) => void;
}

function RulesTable({ label, rules, categoryNames, onEdit, onDelete }: RulesTableProps) {
  const editable = onEdit !== undefined && onDelete !== undefined;
  return (
    <Card className="overflow-hidden">
      <Table aria-label={label} className="table-fixed">
        <colgroup>
          <col />
          <col className="w-44" />
          <col className="w-44" />
          <col className="w-24" />
          {editable ? <col className="w-24" /> : null}
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="px-4">Looks for</TableHead>
            <TableHead className="px-4">Match</TableHead>
            <TableHead className="px-4">Category</TableHead>
            <TableHead className="px-4 text-right">Priority</TableHead>
            {editable ? (
              <TableHead className="px-4">
                <span className="sr-only">Actions</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rules.map((rule) => (
            <TableRow key={rule.id}>
              <TableCell className="px-4">
                <code className="block truncate font-mono text-[0.8125rem]" title={rule.pattern}>
                  {rule.pattern}
                </code>
              </TableCell>
              <TableCell className="text-muted-foreground px-4">
                {matchTypeLabel(rule.match_type)}
              </TableCell>
              <TableCell className="px-4">
                {categoryNames.get(rule.category_id) ?? "Unknown category"}
              </TableCell>
              <TableCell className="px-4 text-right tabular-nums">{rule.priority}</TableCell>
              {editable ? (
                <TableCell className="px-2 text-right">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Edit the rule for ${rule.pattern}`}
                    onClick={() => {
                      onEdit(rule);
                    }}
                  >
                    <Pencil aria-hidden="true" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete the rule for ${rule.pattern}`}
                    onClick={() => {
                      onDelete(rule);
                    }}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function RulesSkeleton() {
  return (
    <div role="status" aria-label="Loading rules" className="flex flex-col gap-3">
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
